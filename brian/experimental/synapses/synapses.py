'''
The Synapses class - see BEP-21
'''
from brian import *
from brian.utils.dynamicarray import *
from spikequeue import *
from synapticvariable import *
import numpy as np
from brian.inspection import *
from brian.equations import *
from numpy.random import binomial
from brian.utils.documentation import flattened_docstring
from random import sample
import re
import warnings

__all__ = ['Synapses']

class Synapses(NeuronGroup): # This way we inherit a lot of useful stuff
    def __init__(self, source, target = None, model = None, 
             max_delay = 0, # is this useful?
             level = 0,
             clock = None,
             unit_checking = True, method = None, freeze = False, implicit = False, order = 1, # model (state updater) related
             pre = None, post = None):
        N=len(source) # initial number of synapses = number of presynaptic neurons
        target=target or source # default is target=source

        # Check clocks. For the moment we enforce the same clocks for all objects
        clock = clock or source.clock
        if source.clock!=target.clock:
            raise ValueError,"Source and target groups must have the same clock"

        # Insert the lastupdate variable if necessary
        expr=re.compile(r'\blastupdate\b')
        if (pre is not None and expr.search(pre) is not None) or \
           (post is not None and expr.search(post) is not None):
            model+='\nlastupdate : second\n'
            if pre is not None:
                pre=flattened_docstring(pre)+'\nlastupdate=t\n'
            if post is not None:
                post=flattened_docstring(post)+'\nlastupdate=t\n'

        NeuronGroup.__init__(self, 0,model=model,clock=clock,level=level+1,unit_checking=unit_checking,method=method,freeze=freeze,implicit=implicit,order=order)
        # We might want *not* to use the state updater on all variables, so for now I disable it (see update())
        '''
        At this point we have:
        * a state matrix _S with all variables
        * units, state dictionary with each value being a row of _S + the static equations
        * subgroups of synapses
        * link_var (i.e. we can link two synapses objects)
        * __len__
        * __setattr__: we can write S.w=array of values
        * var_index is a dictionary from names to row index in _S
        * num_states()
        
        Things we have that we don't want:
        * LS structure (but it will not be filled since the object does not spike)
        * (from Group) __getattr_ needs to be rewritten
        * a complete state updater, but we need to extract parameters and event-driven parts
        * The state matrix is not dynamic
        
        Things we may need to add:
        * _pre and _post suffixes
        '''
        self.source=source
        self.target=target
        # Set last spike to -infinity
        if 'lastupdate' in self.var_index:
            self.lastupdate=-1e6
        # _S is turned to a dynamic array - OK this is probably not good! we may lose references at this point
        S=self._S
        self._S=DynamicArray(S.shape)
        self._S[:]=S

        # Pre and postsynaptic indexes (synapse -> pre/post)
        self.presynaptic=DynamicArray(len(self),dtype=smallest_inttype(len(self.source))) # this should depend on number of neurons
        self.postsynaptic=DynamicArray(len(self),dtype=smallest_inttype(len(self.target))) # this should depend on number of neurons

        # Pre and postsynaptic delays (synapse -> delay_pre/delay_post)
        self._delay_pre=DynamicArray(len(self),dtype=int16) # max 32767 delays
        self._delay_post=DynamicArray(len(self),dtype=int16)
        
        # Pre and postsynaptic synapses (i->synapse indexes)
        max_synapses=2147483647 # it could be explicitly reduced by a keyword
        # We use a loop instead of *, otherwise only 1 dynamic array is created
        self.synapses_pre=[DynamicArray(0,dtype=smallest_inttype(max_synapses)) for _ in range(len(self.source))]
        self.synapses_post=[DynamicArray(0,dtype=smallest_inttype(max_synapses)) for _ in range(len(self.target))]

        # Code generation
        class Replacer(object):
            def __init__(self, func, n):
                self.n = n
                self.func = func
            def __call__(self):
                return self.func(self.n)
        self._Replacer = Replacer

        self.contained_objects = []
        self.pre_code,self.pre_namespace=self.generate_code(pre,level+1)
        self.pre_queue = SpikeQueue(self.source, self.synapses_pre, self._delay_pre, max_delay = max_delay)
        self.contained_objects.append(self.pre_queue)
        
        if post is not None:
            self.post_code,self.post_namespace=self.generate_code(post,level+1,direct=True)
            self.post_queue = SpikeQueue(self.target, self.synapses_post, self._delay_post, max_delay = max_delay)
            self.contained_objects.append(self.post_queue)
        else:
            self.post_code=None
      
    def generate_code(self,code,level,direct=False):
        '''
        Generates pre and post code.
        
        If ``direct'' is True, the code is generated assuming that
        postsynaptic variables are not modified.
        
        TODO:
        * include static variables
        * have a list of variable names
        * deal with v_post, v_pre
        '''
        # Handle multi-line pre, post equations and multi-statement equations separated by ;
        # (this should probably be factored)
        if '\n' in code:
            code = flattened_docstring(code)
        elif ';' in code:
            code = '\n'.join([line.strip() for line in code.split(';')])
        
        # Create namespaces
        _namespace = namespace(code, level = level + 1)
        _namespace['target'] = self.target # maybe we could save one indirection here
        _namespace['unique'] = np.unique
        _namespace['nonzero'] = np.nonzero

        # Replace rand() by vectorised version
        # TODO: pass number of synapses
        #pre = re.sub(r'\b' + 'rand\(\)', 'rand(len(_i))', pre)

        # Generate the code
        def update_code(code, indices):
            res = code
            # given the synapse indices, write the update code,
            # this is here because in the code we generate we need to write this twice (because of the multiple presyn spikes for the same postsyn neuron problem)
                       
            # Replace synaptic variables by their value
            for var in self.var_index: # static variables are not included here
                if isinstance(var, str):
                    res = re.sub(r'\b' + var + r'\b', var + '['+indices+']', res) # synaptic variable, indexed by the synapse number
 
            # Replace postsynaptic variables by their value
            for postsyn_var in self.target.var_index: # static variables are not included here
                if isinstance(postsyn_var, str):
                    res = re.sub(r'\b' + postsyn_var + r'\b', 'target.' + postsyn_var + '[_post['+indices+']]', res)# postsyn variable, indexed by post syn neuron numbers
 
            return res
 
        if direct: # direct update code, not caring about multiple accesses to postsynaptic variables
            code_str=update_code(code, '_synapses') + "\n"            
        else:
            code_str = "_post_neurons = _post[_synapses]\n" # not necessary to do a copy because _synapses is not a slice
            code_str += "_u, _i = unique(_post_neurons, return_index = True)\n"
            code_str += update_code(code, '_synapses[_i]') + "\n"
            code_str += "if len(_u) < len(_post_neurons):\n"
            code_str += "    _post_neurons[_i] = -1\n"
            code_str += "    while (len(_u) < len(_post_neurons)) & (_post_neurons>-1).any():\n" # !! the any() is time consuming (len(u)>=1??)
            #code_str += "    while (len(_u) < len(_post_neurons)) & (len(_u)>1):\n" # !! the any() is time consuming (len(u)>=1??)
            code_str += "        _u, _i = unique(_post_neurons, return_index = True)\n"
            code_str += indent(update_code(code, '_synapses[_i[1:]]'),2) + "\n"
            code_str += "        _post_neurons[_i[1:]] = -1 \n"
            
        log_debug('brian.synapses', '\nPRE CODE:\n'+code_str)
        
        # Commpile
        compiled_code = compile(code_str, "Synaptic code", "exec")
        
        return compiled_code,_namespace

    def __setitem__(self, key, value):
        '''
        Creates new synapses.
        Synapse indexes are created such that synapses with the same presynaptic neuron
        and delay have contiguous indexes.
        
        Caution:
        1) there is no deletion
        2) synapses are added, not replaced (e.g. S[1,2]=True;S[1,2]=True creates 2 synapses)
        
        TODO:
        * S[:,:]=array (boolean or int)
        '''
        if not isinstance(key, tuple): # we should check that number of elements is 2 as well
            raise ValueError('Synapses behave as 2-D objects')
        pre,post=key # pre and post indexes (can be slices)
        
        '''
        Each of these sets of statements creates:
        * synapses_pre: a mapping from presynaptic neuron to synapse indexes
        * synapses_post: same
        * presynaptic: an array of presynaptic neuron indexes (synapse->pre)
        * postsynaptic: same
        '''
        pre_slice = self.presynaptic_indexes(pre)
        post_slice = self.postsynaptic_indexes(post)
        # Bound checks
        if pre_slice[-1]>=len(self.source):
            raise ValueError('Presynaptic index greater than number of presynaptic neurons')
        if post_slice[-1]>=len(self.target):
            raise ValueError('Postsynaptic index greater than number of postsynaptic neurons')

        if isinstance(value,float):
            self.connect_random(pre,post,value)
            return
        elif isinstance(value, (int, bool)): # ex. S[1,7]=True
            # Simple case, either one or multiple synapses between different neurons
            if value is False:
                raise ValueError('Synapses cannot be deleted')
            elif value is True:
                nsynapses = 1
            else:
                nsynapses = value

            postsynaptic,presynaptic=meshgrid(post_slice,pre_slice) # synapse -> pre, synapse -> post
            # Flatten
            presynaptic.shape=(presynaptic.size,)
            postsynaptic.shape=(postsynaptic.size,)
            # pre,post -> synapse index, relative to last synapse
            # (that's a complex vectorised one!)
            synapses_pre=arange(len(presynaptic)).reshape((len(pre_slice),len(post_slice)))
            synapses_post=ones((len(post_slice),1),dtype=int)*arange(0,len(presynaptic),len(post_slice))+\
                          arange(len(post_slice)).reshape((len(post_slice),1))
            # Repeat
            if nsynapses>1:
                synapses_pre=hstack([synapses_pre+k*len(presynaptic) for k in range(nsynapses)]) # could be vectorised
                synapses_post=hstack([synapses_post+k*len(presynaptic) for k in range(nsynapses)]) # could be vectorised
                presynaptic=presynaptic.repeat(nsynapses)
                postsynaptic=postsynaptic.repeat(nsynapses)
            # Make sure the type is correct
            synapses_pre=array(synapses_pre,dtype=self.synapses_pre[0].dtype)
            synapses_post=array(synapses_post,dtype=self.synapses_post[0].dtype)
            # Turn into dictionaries
            synapses_pre=dict(zip(pre_slice,synapses_pre))
            synapses_post=dict(zip(post_slice,synapses_post))
        elif isinstance(value,str): # string code assignment
            code = re.sub(r'\b' + 'rand\(\)', 'rand(n)', value) # replacing rand()
            code = re.sub(r'\b' + 'randn\(\)', 'randn(n)', code) # replacing randn()
            _namespace = namespace(value, level=1)
            _namespace.update({'j' : post_slice,
                               'n' : len(post_slice),
                               'rand': np.random.rand,
                               'randn': np.random.randn})
            synapses_pre={}
            nsynapses=0
            presynaptic,postsynaptic=[],[]
            for i in pre_slice:
                _namespace['i']=i # maybe an array rather than a scalar?
                result = eval(code, _namespace) # mask on synapses
                if result.dtype==float: # random number generation
                    result=rand(len(post_slice))<result
                indexes=result.nonzero()[0]
                n=len(indexes)
                synapses_pre[i]=array(nsynapses+arange(n),dtype=self.synapses_pre[0].dtype)
                presynaptic.append(i*ones(n,dtype=int))
                postsynaptic.append(post_slice[indexes])
                nsynapses+=n
            
            # Make sure the type is correct
            presynaptic=array(hstack(presynaptic),dtype=self.presynaptic.dtype)
            postsynaptic=array(hstack(postsynaptic),dtype=self.postsynaptic.dtype)
            synapses_post=None
        elif isinstance(value, np.ndarray):
            raise NotImplementedError
            nsynapses = array(value, dtype = int) 
            
        # Now create the synapses
        self.create_synapses(presynaptic,postsynaptic,synapses_pre,synapses_post)
    
    def create_synapses(self,presynaptic,postsynaptic,synapses_pre=None,synapses_post=None):
        '''
        Create new synapses.
        * synapses_pre: a mapping from presynaptic neuron to synapse indexes
        * synapses_post: same
        * presynaptic: an array of presynaptic neuron indexes (synapse->pre)
        * postsynaptic: same
        
        If synapses_pre or synapses_post is not specified, it is calculated from
        presynaptic or postsynaptic.       
        '''
        # Resize dynamic arrays and push new values
        newsynapses=len(presynaptic) # number of new synapses
        nvars,nsynapses_all=self._S.shape
        self._S.resize((nvars,nsynapses_all+newsynapses))
        self.presynaptic.resize(nsynapses_all+newsynapses)
        self.presynaptic[nsynapses_all:]=presynaptic
        self.postsynaptic.resize(nsynapses_all+newsynapses)
        self.postsynaptic[nsynapses_all:]=postsynaptic
        self._delay_pre.resize(nsynapses_all+newsynapses)
        self._delay_post.resize(nsynapses_all+newsynapses)
        if synapses_pre is None:
            synapses_pre=invert_array(presynaptic,dtype=self.synapses_post[0].dtype)
        for i,synapses in synapses_pre.iteritems():
            nsynapses=len(self.synapses_pre[i])
            self.synapses_pre[i].resize(nsynapses+len(synapses))
            self.synapses_pre[i][nsynapses:]=synapses+nsynapses_all # synapse indexes are shifted
        if synapses_post is None:
            synapses_post=invert_array(postsynaptic,dtype=self.synapses_post[0].dtype)
        for j,synapses in synapses_post.iteritems():
            nsynapses=len(self.synapses_post[j])
            self.synapses_post[j].resize(nsynapses+len(synapses))
            self.synapses_post[j][nsynapses:]=synapses+nsynapses_all
    
    def __getattr__(self, name):
        if name == 'var_index':
            raise AttributeError
        if not hasattr(self, 'var_index'):
            raise AttributeError
        if (name=='delay_pre') or (name=='delay'): # default: delay is presynaptic delay
            return SynapticDelayVariable(self._delay_pre,self)
        elif name=='delay_post':
            return SynapticDelayVariable(self._delay_post,self)
        try:
            x=self.state(name)
            return SynapticVariable(x,self)
        except KeyError:
            return NeuronGroup.__getattr__(self,name)
        
    def __setattr__(self, name, val):
        if (name=='delay_pre') or (name=='delay'):
            SynapticDelayVariable(self._delay_pre,self)[:]=val
        elif name=='delay_post':
            SynapticDelayVariable(self._delay_post,self)[:]=val
        else: # copied from Group
            origname = name
            if len(name) and name[-1] == '_':
                origname = name[:-1]
            if not hasattr(self, 'var_index') or (name not in self.var_index and origname not in self.var_index):
                object.__setattr__(self, name, val)
            else:
                if name in self.var_index:
                    x=self.state(name)
                else:
                    x=self.state_(origname)
                SynapticVariable(x,self).__setitem__(slice(None,None,None),val,level=2)
        
    def update(self): # this is called at every timestep
        '''
        TODO:
        * Have namespaces partially built at run time (call state_(var)),
          or better, extract synaptic events from the synaptic state matrix;
          same stuff for postsynaptic variables
        * Deal with static variables
        * Factor code
        '''
        #NeuronGroup.update(self) # we don't do it for now
        synaptic_events = self.pre_queue.peek()
        if len(synaptic_events):
            # Build the namespace - Maybe we should do this only once? (although there is the problem of static equations)
            # Careful: for dynamic arrays you need to get fresh references at run time
            _namespace = self.pre_namespace
            #_namespace['_synapses'] = synaptic_events # not needed any more
            #for var in self.var_index: # in fact I should filter out integers ; also static variables are not included here
            #    if isinstance(var, str):
            #        _namespace[var] = self.state_(var)[synaptic_events] # could be faster to directly extract a submatrix from _S
            for var,i in self.var_index.iteritems(): # no static variables here
                if isinstance(var, str):
                    _namespace[var]=self._S[i,:]
            _namespace['_synapses']=synaptic_events
            _namespace['t'] = self.clock._t
            _namespace['_pre']=self.presynaptic
            _namespace['_post']=self.postsynaptic
            _namespace['n'] = len(synaptic_events)
            _namespace['rand'] = self._Replacer(np.random.rand, len(synaptic_events))
            _namespace['randn'] = self._Replacer(np.random.randn, len(synaptic_events))
            exec self.pre_code in _namespace
        self.pre_queue.next()
        
        if self.post_code is not None: # factor this
            synaptic_events = self.post_queue.peek()
            if len(synaptic_events):
                # Build the namespace - Maybe we should do this only once? (although there is the problem of static equations)
                # Careful: for dynamic arrays you need to get fresh references at run time
                _namespace = self.post_namespace
                #_namespace['_synapses'] = synaptic_events # not needed any more
                #for var in self.var_index: # in fact I should filter out integers ; also static variables are not included here
                #    if isinstance(var, str):
                #        _namespace[var] = self.state_(var)[synaptic_events] # could be faster to directly extract a submatrix from _S
                for var,i in self.var_index.iteritems(): # no static variables here
                    if isinstance(var, str):
                        _namespace[var]=self._S[i,:]
                _namespace['_synapses']=synaptic_events
                _namespace['t'] = self.clock._t
                _namespace['_pre']=self.presynaptic
                _namespace['_post']=self.postsynaptic
                _namespace['n'] = len(synaptic_events)
                _namespace['rand'] = self._Replacer(np.random.rand, len(synaptic_events))
                _namespace['randn'] = self._Replacer(np.random.randn, len(synaptic_events))
                exec self.post_code in _namespace
            self.post_queue.next()

    def connect_random(self,pre=None,post=None,sparseness=None):
        '''
        Creates random connections between pre and post neurons
        (default: all neurons).
        '''
        if pre is None:
            pre=self.source
        if post is None:
            post=self.target
        pre,post=self.presynaptic_indexes(pre),self.postsynaptic_indexes(post)
        m=len(post)
        synapses_pre={}
        nsynapses=0
        presynaptic,postsynaptic=[],[]
        for i in pre: # vectorised over post neurons
            k = binomial(m, sparseness, 1)[0] # number of postsynaptic neurons
            synapses_pre[i]=nsynapses+arange(k)
            presynaptic.append(i*ones(k,dtype=int))
            # Not significantly faster to generate all random numbers in one pass
            # N.B.: the sample method is implemented in Python and it is not in Scipy
            postneurons = sample(xrange(m), k)
            #postneurons.sort() # sorting is unnecessary
            postsynaptic.append(post[postneurons])
            nsynapses+=k
        presynaptic=hstack(presynaptic)
        postsynaptic=hstack(postsynaptic)
        synapses_post=None # we ask for automatic calculation of (post->synapse)
        # this is more or less given by unique
        self.create_synapses(presynaptic,postsynaptic,synapses_pre,synapses_post)
        '''
        TODO NOW:
        * automatic calculation of post->synapse
        '''
        
    def presynaptic_indexes(self,x):
        '''
        Returns the array of presynaptic neuron indexes corresponding to x,
        which can be a integer, an array or a subgroup
        '''
        return neuron_indexes(x,self.source)

    def postsynaptic_indexes(self,x):
        '''
        Returns the array of postsynaptic neuron indexes corresponding to x,
        which can be a integer, an array or a subgroup
        '''
        return neuron_indexes(x,self.target)
    
    def compress(self):
        # Check that the object is not empty
        if len(self)==0:
            warnings.warn("Empty Synapses object")
    
    def __repr__(self):
        return 'Synapses object with '+ str(len(self))+ ' synapses'

def smallest_inttype(N):
    '''
    Returns the smallest dtype that can store N indexes
    '''
    if N<=127:
        return int8
    elif N<=32727:
        return int16
    elif N<=2147483647:
        return int32
    else:
        return int64

def indent(s,n=1):
    return re.compile(r'^',re.M).sub('    '*n,s)

def invert_array(x,dtype=int):
    '''
    Returns a dictionary y of N int arrays such that:
    y[i]=set of j such that x[j]==i
    '''
    I = argsort(x) # ,kind='mergesort') # uncomment for a stable sort
    xs = x[I]
    u,indices=unique(xs,return_index=True)
    y={}
    for j,i in enumerate(u[:-1]):
        y[i]=array(I[indices[j]:indices[j+1]],dtype=dtype)
    y[u[-1]]=array(I[indices[-1]:],dtype=dtype)
    return y

if __name__=='__main__':
    #log_level_debug()
    print invert_array(array([7,5,2,2,3,5]))