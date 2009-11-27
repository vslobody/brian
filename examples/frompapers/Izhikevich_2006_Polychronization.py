'''
Polychronization: Computation with Spikes
Eugene M. Izhikevich
Neural Computation, 2006
'''
from brian import *
import random

defaultclock.dt = 0.5*ms

M = 100                # number of synapses per neuron
D = 20*ms              # maximal conduction delay
D_min = 1*ms           # minimal conduction delay
D_i = 1*ms             # inhibitory neuron conduction delay

# excitatory neurons
Ne = 800
a_e = 0.02/ms
d_e = 8*mV/ms
s_e = 6*mV
# inhibitory neurons
Ni = 200
a_i = 0.1/ms
d_i = 2*mV/ms
s_i = -5*mV
# all neurons
b = 0.2/ms
c = -65*mV
sm = 10*mV             # maximal synaptic strength
N = Ne+Ni

thalamic_input_weight = 20*mV

eqs = Equations('''
dv/dt = (0.04/ms/mV)*v**2+(5/ms)*v+140*mV/ms-u : volt
du/dt = a*(b*v-u)                              : volt/second
a                                              : 1/second
d                                              : volt/second
''')
reset = '''
v = c
u += d
'''
threshold = 30*mV

G = NeuronGroup(N, eqs, threshold=threshold, reset=reset)
Ge = G.subgroup(Ne)
Gi = G.subgroup(Ni)

G.v = c
G.u = 0.2*c
Ge.a = a_e
Ge.d = d_e
Gi.a = a_i
Gi.d = d_i

@network_operation
def random_thalamic_input():
    G.v[randint(N)] += float(thalamic_input_weight)

Ce = Connection(Ge, G, 'v', delay=True, max_delay=D)
Ci = Connection(Gi, Ge, 'v', delay=D_i)

for i in xrange(Ne):
    inds = random.sample(xrange(N), M)
    Ce[i, inds] = s_e*ones(len(inds))
    Ce.delay[i, inds] = rand(len(inds))*(D-D_min)+D_min
for i in xrange(Ni):
    inds = random.sample(xrange(Ne), M)
    Ci[i, inds] = s_i*ones(len(inds))

# Can't use standard STDP object as Izhikevich uses a strange rule with STDP
# acting on the weight derivative, which is updated every second. Implementing
# this requires a change to STDP so that you can specify an alternative weight
# matrix w to act on - this should be easy to add though.

# Simplified version of Izhikevich's rule 
#stdp = ExponentialSTDP(Ce, taup=20*ms, taum=20*ms, Ap=0.1*3, Am=-0.12*3,#Ap=0.1*mV/sm*9.5, Am=-0.12*mV/sm*9.5,
#                       wmax=sm, interactions='nearest')
#stdp = ExponentialSTDP(Ce, taup=20*ms, taum=20*ms, Ap=0, Am=0,
#                       wmax=sm, interactions='nearest')
#del stdp
#import gc
#gc.collect()

#@network_operation(clock=EventClock(dt=1*second))
#def f():
#    Ce.W.alldata[:] = clip(Ce.W.alldata[:]+0.01*sm, 0, sm)

#M = SpikeMonitor(G)

print G.period, G.period*defaultclock.dt
print G._max_delay, G._max_delay*defaultclock.dt
#exit()

#ion()
M1 = SpikeMonitor(G)
run(1*second, report='stderr')
raster_plot(M1)
#draw()
#forget(M1)
#run(99*second, report='stderr')
#M2 = SpikeMonitor(G)
#run(1*second, report='stderr')
#figure()
#raster_plot(M2)
##draw()
##forget(M2)
##run((3600-101)*second, report='stderr')
##M3 = SpikeMonitor(G)
##run(1*second, report='stderr')
#ioff()
##figure()
##raster_plot(M3)
show()