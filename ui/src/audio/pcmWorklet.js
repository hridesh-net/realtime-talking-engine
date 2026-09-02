// Microphone capture for the Gemini Live path.
//
// The Live API wants raw 16-bit little-endian PCM at 16 kHz, mono. The browser
// gives us Float32 in 128-sample render quanta, so this batches them up and
// converts. It runs on the audio thread, which is the point: a ScriptProcessor
// on the main thread glitches the moment React re-renders.
//
// It does NOT denoise, gate or gain-adjust anything. Noise suppression is the
// browser's own (a getUserMedia constraint the operator can switch off), and
// the stereo recording is tapped from the same raw mic — it is the evidence the
// report engine checks quotes against, so nothing may quietly rewrite it here.

// ~128 ms per message at 16 kHz. Small enough that turn detection stays snappy,
// large enough that we are not posting a message every 8 ms.
const BATCH_SAMPLES = 2048

class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(BATCH_SAMPLES)
    this.filled = 0
  }

  flush() {
    const pcm = new Int16Array(this.filled)
    let sumSquares = 0
    for (let i = 0; i < this.filled; i++) {
      const sample = Math.max(-1, Math.min(1, this.buffer[i]))
      sumSquares += sample * sample
      // Asymmetric on purpose: Int16 runs -32768..32767, so scaling negatives
      // by 32767 would clip a full-scale negative peak by one LSB.
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
    }
    this.filled = 0
    // Transfer the buffer rather than copying it — this fires ~8 times a second
    // for the length of the interview.
    this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(sumSquares / (pcm.length || 1)) }, [
      pcm.buffer,
    ])
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    for (let i = 0; i < channel.length; i++) {
      this.buffer[this.filled++] = channel[i]
      if (this.filled === BATCH_SAMPLES) this.flush()
    }
    return true
  }
}

registerProcessor('pcm-worklet', PCMWorklet)
