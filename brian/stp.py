'''
Short-term synaptic plasticity.

Implements the short-term plasticity model described in:
Markram et al (1998). Differential signaling via the same axon of
neocortical pyramidal neurons, PNAS. Synaptic dynamics is
described by two variables x and u, which follows the following differential equations::

  dx/dt=(1-x)/taud  (depression)
  du/dt=(U-u)/tauf  (facilitation)

where taud, tauf are time constants and U is a parameter in 0..1. Each a presynaptic
spike triggers modifications of the variables::

  u<-u+U*(1-u)
  x<-x*(1-u)

Synaptic weights are modulated by the product u*x (in 0..1) (before update).
'''
# See BEP-1

from network import NetworkOperation
from neurongroup import NeuronGroup
from monitor import SpikeMonitor
from scipy import zeros,exp
from connection import DelayConnection

__all__=['STP']

class STPGroup(NeuronGroup):
    '''
    Neuron group forwarding spikes with short term plasticity modulation.
    '''
    def __init__(self,N):
        eqs='''
        ux : 1
        x : 1
        u : 1
        '''
        NeuronGroup.__init__(self,N,model=eqs)
        
    def update(self):
        pass

class STPUpdater(SpikeMonitor):
    '''
    Event-driven updates of STP variables.
    '''
    def __init__(self,source,P,taud,tauf,U,delay=0):
        SpikeMonitor.__init__(self,source,record=False,delay=delay)
        # P is the group with the STP variables
        N=len(P)
        self.P=P
        self.minvtaud=-1./taud
        self.minvtauf=-1./tauf
        self.U=U
        self.ux=P.ux
        self.x=P.x
        self.u=P.u
        self.lastt=zeros(N) # last update
        self.clock=P.clock
        
    def propagate(self,spikes):
        self.ux[spikes]=self.u[spikes]*self.x[spikes]
        interval=self.clock.t-self.lastt[spikes]
        self.u[spikes]=self.U+(self.u[spikes]-self.U)*exp(interval*self.minvtauf)
        tmp=1-self.u[spikes]
        self.x[spikes]=(1+(self.x[spikes]-1)*exp(interval*self.minvtaud))*tmp
        self.u[spikes]+=self.U*tmp
        self.lastt[spikes]=self.clock.t
        self.P.LS.push(spikes)

class STP(NetworkOperation):
    '''
    Short-term synaptic plasticity, following the Tsodyks-Markram model.

    Implements the short-term plasticity model described in Markram et al (1998).
    Differential signaling via the same axon of
    neocortical pyramidal neurons, PNAS.
    Synaptic dynamics is described by two variables x and u, which follow
    the following differential equations::
    
      dx/dt=(1-x)/taud  (depression)
      du/dt=(U-u)/tauf  (facilitation)
    
    where taud, tauf are time constants and U is a parameter in 0..1. Each presynaptic
    spike triggers modifications of the variables::
    
      u<-u+U*(1-u)
      x<-x*(1-u)
    
    Synaptic weights are modulated by the product ``u*x`` (in 0..1) (before update).
    
    Reference:
    
    * Markram et al (1998). "Differential signaling via the same axon of
      neocortical pyramidal neurons", PNAS.
    '''
    def __init__(self,C,taud,tauf,U):
        if isinstance(C,DelayConnection):
            raise AttributeError,"STP does not handle heterogeneous connections yet."
        NetworkOperation.__init__(self,lambda:None)
        N=len(C.source)
        P=STPGroup(N)
        P.x=1
        P.u=U
        P.ux=U
        updater=STPUpdater(C.source,P,taud,tauf,U,delay=C.delay*C.source.clock.dt)
        self.contained_objects=[updater]
        C.source=P
        C.delay=0
        C._nstate_mod=0 # modulation of synaptic weights
        self.vars = P
        
    def __call__(self):
        pass
