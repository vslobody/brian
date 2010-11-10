'''
FIR filterbank, can be treated as a special case of LinearFilterbank, but an
optimisation is possible using buffered output by using FFT based convolution
as in HRTF.apply. To do this is slightly tricky because it needs to cache
previous inputs. For the moment, we implement it as a special case of
LinearFilterbank but later this will change to using the FFT method.
'''
from brian import *
from filterbank import *
from linearfilterbank import *

__all__ = ['FIRFilterbank', 'LinearFIRFilterbank', 'FFTFIRFilterbank']

class LinearFIRFilterbank(LinearFilterbank):
    def __init__(self, source, impulseresponse):
        # if a 1D impulse response is given we apply it to every channel
        # Note that because we are using LinearFilterbank at the moment, this
        # means duplicating the impulse response. However, it could be stored
        # just once when we move to using FFT based convolution and in fact this
        # will save a lot of computation as the FFT only needs to be computed
        # once then.
        if len(impulseresponse.shape)==1:
            impulseresponse = repeat(reshape(impulseresponse, (1, len(impulseresponse))), source.nchannels, axis=0)
        # Automatically duplicate mono input to fit the desired output shape
        if impulseresponse.shape[0]!=source.nchannels:
            if source.nchannels!=1:
                raise ValueError('Can only automatically duplicate source channels for mono sources, use RestructureFilterbank.')
            source = RestructureFilterbank(source, impulseresponse.shape[0])
        # Implement it as a LinearFilterbank
        b = reshape(impulseresponse, impulseresponse.shape+(1,))
        a = zeros_like(b)
        a[:, 0, :] = 1
        LinearFilterbank.__init__(self, source, b, a)

class FFTFIRFilterbank(Filterbank):
    def __init__(self, source, impulseresponse):
        # if a 1D impulse response is given we apply it to every channel
        # Note that because we are using LinearFilterbank at the moment, this
        # means duplicating the impulse response. However, it could be stored
        # just once when we move to using FFT based convolution and in fact this
        # will save a lot of computation as the FFT only needs to be computed
        # once then.
        if len(impulseresponse.shape)==1:
            impulseresponse = repeat(reshape(impulseresponse, (1, len(impulseresponse))), source.nchannels, axis=0)
        # Automatically duplicate mono input to fit the desired output shape
        if impulseresponse.shape[0]!=source.nchannels:
            if source.nchannels!=1:
                raise ValueError('Can only automatically duplicate source channels for mono sources, use RestructureFilterbank.')
            source = RestructureFilterbank(source, impulseresponse.shape[0])
        Filterbank.__init__(self, source)

        self.input_cache = zeros((impulseresponse.shape[1], self.nchannels))
        self.impulseresponse = impulseresponse
        self.fftcache_nmax = -1

    def buffer_init(self):
        Filterbank.buffer_init(self)
        self.input_cache[:] = 0
    
    def buffer_apply(self, input):
        output = zeros_like(input)
        nmax = max(self.input_cache.shape[0]+input.shape[0], self.impulseresponse.shape[1])
        nmax = 2**int(ceil(log2(nmax)))
        if self.fftcache_nmax!=nmax:
            self.fftcache = []
        for i, (previnput, curinput, ir) in enumerate(zip(self.input_cache.T,
                                                          input.T,
                                                          self.impulseresponse)):
            fullinput = hstack((previnput, curinput))
            # pad
            fullinput = hstack((fullinput, zeros(nmax-len(fullinput))))
            # apply fft
            if self.fftcache_nmax!=nmax:
                # recompute IR fft, first pad, then take fft, then store
                ir = hstack((ir, zeros(nmax-len(ir))))
                ir_fft = fft(ir, n=nmax)
                self.fftcache.append(ir_fft)
            else:
                ir_fft = self.fftcache[i]
            fullinput_fft = fft(fullinput, n=nmax)
            curoutput_fft = fullinput_fft*ir_fft
            curoutput = ifft(curoutput_fft)
            # unpad
            curoutput = curoutput[len(previnput):len(previnput)+len(curinput)]
            output[:, i] = curoutput
        if self.fftcache_nmax!=nmax:
            self.fftcache_nmax = nmax
        # update input cache
        nic = self.input_cache.shape[0]
        ni = input.shape[0]
        #print ni, nic
        if ni>=nic:
            self.input_cache[:, :] = input[-nic:, :]
        else:
            self.input_cache[:-ni, :] = self.input_cache[ni:, :]
            self.input_cache[-ni:, :] = input
        return output


class FIRFilterbank(Filterbank):
    '''
    Finite impulse response filterbank
    
    Initialisation parameters:
    
    ``source``
        Source sound or filterbank.
    ``impulseresponse``
        Either a 1D array providing a single impulse response applied to every
        input channel, or a 2D array of shape ``(nchannels, ir_length)`` for
        ``ir_length`` the number of samples in the impulse response. Note that
        if you are using a multichannel sound ``x`` as a set of impulse responses,
        the array should be ``impulseresponse=array(x.T)``.
    '''
    def __init__(self, source, impulseresponse, use_linearfilterbank=False):
        if use_linearfilterbank:
            self.__class__ = LinearFIRFilterbank
        else:
            self.__class__ = FFTFIRFilterbank
        self.__init__(source, impulseresponse)
