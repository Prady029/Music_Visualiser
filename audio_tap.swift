import Foundation
import CoreAudio
import AudioToolbox
import os

private let stopFlag = ManagedAtomicBool()
private let restartFlag = ManagedAtomicBool()

final class ManagedAtomicBool {
    private var lock = os_unfair_lock_s()
    private var value = false

    func set(_ newValue: Bool) {
        os_unfair_lock_lock(&lock)
        value = newValue
        os_unfair_lock_unlock(&lock)
    }

    func get() -> Bool {
        os_unfair_lock_lock(&lock)
        let current = value
        os_unfair_lock_unlock(&lock)
        return current
    }
}

final class FloatRingBuffer {
    private var lock = os_unfair_lock_s()
    private var buffer: [Float]
    private var readIndex = 0
    private var writeIndex = 0
    private var count = 0
    private let capacity: Int

    init(capacity: Int) {
        self.capacity = capacity
        self.buffer = [Float](repeating: 0, count: capacity)
    }

    func push(_ ptr: UnsafePointer<Float>, count n: Int, stride: Int = 1) {
        os_unfair_lock_lock(&lock)
        for i in 0..<n {
            if count == capacity {
                readIndex = (readIndex + 1) % capacity
                count -= 1
            }
            buffer[writeIndex] = ptr[i * stride]
            writeIndex = (writeIndex + 1) % capacity
            count += 1
        }
        os_unfair_lock_unlock(&lock)
    }

    func pushFirstTwoChannels(_ ptr: UnsafePointer<Float>, frames: Int, channelCount: Int) {
        os_unfair_lock_lock(&lock)
        for f in 0..<frames {
            if count + 2 > capacity {
                let drop = min(count, 2)
                readIndex = (readIndex + drop) % capacity
                count -= drop
            }
            let base = f * channelCount
            buffer[writeIndex] = ptr[base]
            writeIndex = (writeIndex + 1) % capacity
            buffer[writeIndex] = ptr[base + 1]
            writeIndex = (writeIndex + 1) % capacity
            count += 2
        }
        os_unfair_lock_unlock(&lock)
    }

    func pushInterleavedStereo(left: UnsafePointer<Float>, right: UnsafePointer<Float>, frames: Int) {
        os_unfair_lock_lock(&lock)
        for i in 0..<frames {
            if count + 2 > capacity {
                let drop = min(count, 2)
                readIndex = (readIndex + drop) % capacity
                count -= drop
            }
            buffer[writeIndex] = left[i]
            writeIndex = (writeIndex + 1) % capacity
            buffer[writeIndex] = right[i]
            writeIndex = (writeIndex + 1) % capacity
            count += 2
        }
        os_unfair_lock_unlock(&lock)
    }

    func pop(into out: inout [Float]) -> Int {
        os_unfair_lock_lock(&lock)
        let toRead = min(count, out.count)
        for i in 0..<toRead {
            out[i] = buffer[readIndex]
            readIndex = (readIndex + 1) % capacity
        }
        count -= toRead
        os_unfair_lock_unlock(&lock)
        return toRead
    }
}

func getCFStringProperty(
    objectID: AudioObjectID,
    selector: AudioObjectPropertySelector,
    scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal
) -> String? {
    var address = AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: scope,
        mElement: kAudioObjectPropertyElementMain
    )
    var cfStr: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let status = AudioObjectGetPropertyData(objectID, &address, 0, nil, &size, &cfStr)
    guard status == noErr, let str = cfStr?.takeRetainedValue() else {
        return nil
    }
    return str as String
}

func getDefaultOutputDeviceUID() -> String? {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultOutputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var deviceID: AudioObjectID = kAudioObjectUnknown
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID)
    guard status == noErr, deviceID != kAudioObjectUnknown else {
        return nil
    }
    return getCFStringProperty(objectID: deviceID, selector: kAudioDevicePropertyDeviceUID)
}

@available(macOS 14.2, *)
func getTapFormat(tapID: AudioObjectID) -> AudioStreamBasicDescription? {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioTapPropertyFormat,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    var asbd = AudioStreamBasicDescription()
    var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    let status = AudioObjectGetPropertyData(tapID, &address, 0, nil, &size, &asbd)
    guard status == noErr else {
        return nil
    }
    return asbd
}

func getDeviceInputFormat(deviceID: AudioObjectID) -> AudioStreamBasicDescription? {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyStreamFormat,
        mScope: kAudioObjectPropertyScopeInput,
        mElement: kAudioObjectPropertyElementMain
    )
    var asbd = AudioStreamBasicDescription()
    var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &asbd)
    guard status == noErr else {
        return nil
    }
    return asbd
}

func writeAllFD(_ fd: Int32, _ ptr: UnsafeRawPointer, _ count: Int) -> Bool {
    var offset = 0
    while offset < count {
        let written = Darwin.write(fd, ptr.advanced(by: offset), count - offset)
        if written <= 0 {
            return false
        }
        offset += written
    }
    return true
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

@available(macOS 14.2, *)
func runCaptureSession(headerSent: inout Bool) -> Bool {
    restartFlag.set(false)

    let tapDesc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
    tapDesc.name = "MusicVizTap"
    tapDesc.isPrivate = true
    tapDesc.muteBehavior = .unmuted

    var tapID: AudioObjectID = kAudioObjectUnknown
    var status = AudioHardwareCreateProcessTap(tapDesc, &tapID)
    if status != noErr || tapID == kAudioObjectUnknown {
        fail("CoreAudio AudioHardwareCreateProcessTap failed (OSStatus \(status)). Ensure macOS System Audio Recording permission is granted for your terminal.")
    }
    defer { AudioHardwareDestroyProcessTap(tapID) }

    guard let tapUID = getCFStringProperty(objectID: tapID, selector: kAudioTapPropertyUID) else {
        fail("Failed to read tap UID.")
    }

    let tapASBD = getTapFormat(tapID: tapID)

    var aggDesc: [String: Any] = [
        kAudioAggregateDeviceNameKey: "MusicVizAggregateTap",
        kAudioAggregateDeviceUIDKey: "com.musicviz.tap.\(UUID().uuidString)",
        kAudioAggregateDeviceIsPrivateKey: true,
        kAudioAggregateDeviceIsStackedKey: false,
        kAudioAggregateDeviceTapAutoStartKey: true,
        kAudioAggregateDeviceTapListKey: [
            [
                kAudioSubTapUIDKey: tapUID,
                kAudioSubTapDriftCompensationKey: true
            ]
        ]
    ]

    if let outputUID = getDefaultOutputDeviceUID() {
        aggDesc[kAudioAggregateDeviceMainSubDeviceKey] = outputUID
        aggDesc[kAudioAggregateDeviceSubDeviceListKey] = [
            [kAudioSubDeviceUIDKey: outputUID]
        ]
    }

    var aggDeviceID: AudioObjectID = kAudioObjectUnknown
    status = AudioHardwareCreateAggregateDevice(aggDesc as CFDictionary, &aggDeviceID)
    if status != noErr || aggDeviceID == kAudioObjectUnknown {
        fail("AudioHardwareCreateAggregateDevice failed (OSStatus \(status)).")
    }
    defer { AudioHardwareDestroyAggregateDevice(aggDeviceID) }

    var bufferFrames: UInt32 = 512
    var bufAddr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyBufferFrameSize,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    AudioObjectSetPropertyData(
        aggDeviceID,
        &bufAddr,
        0,
        nil,
        UInt32(MemoryLayout<UInt32>.size),
        &bufferFrames
    )

    let devASBD = getDeviceInputFormat(deviceID: aggDeviceID) ?? tapASBD
    let sampleRate = Int((devASBD?.mSampleRate ?? 48000.0).rounded())
    let rawChannels = Int(devASBD?.mChannelsPerFrame ?? 2)
    let outChannels = rawChannels >= 2 ? 2 : 1

    if !headerSent {
        let header = "MVIZ \(sampleRate) \(outChannels)\n"
        let headerBytes = Array(header.utf8)
        let headerOK = headerBytes.withUnsafeBytes { rawBuf in
            writeAllFD(STDOUT_FILENO, rawBuf.baseAddress!, rawBuf.count)
        }
        if !headerOK {
            return false
        }
        headerSent = true
    }

    let ring = FloatRingBuffer(capacity: max(sampleRate * outChannels * 2, 16384))
    let semaphore = DispatchSemaphore(value: 0)

    var ioProcID: AudioDeviceIOProcID?
    status = AudioDeviceCreateIOProcIDWithBlock(&ioProcID, aggDeviceID, nil) { _, inInputData, _, _, _ in
        let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inInputData))
        guard abl.count > 0 else { return }

        if abl.count == 1 {
            let buf = abl[0]
            guard let mData = buf.mData else { return }
            let ch = max(Int(buf.mNumberChannels), 1)
            let totalFloats = Int(buf.mDataByteSize) / MemoryLayout<Float>.size
            let frames = totalFloats / ch
            guard frames > 0 else { return }
            let ptr = mData.assumingMemoryBound(to: Float.self)

            if outChannels == 1 || ch == 1 {
                ring.push(ptr, count: frames, stride: ch)
            } else if ch == 2 {
                ring.push(ptr, count: frames * 2, stride: 1)
            } else {
                ring.pushFirstTwoChannels(ptr, frames: frames, channelCount: ch)
            }
        } else {
            let buf0 = abl[0]
            guard let data0 = buf0.mData else { return }
            let frames = Int(buf0.mDataByteSize) / MemoryLayout<Float>.size
            guard frames > 0 else { return }
            let ptr0 = data0.assumingMemoryBound(to: Float.self)

            if outChannels == 2, abl.count >= 2, let data1 = abl[1].mData {
                let ptr1 = data1.assumingMemoryBound(to: Float.self)
                ring.pushInterleavedStereo(left: ptr0, right: ptr1, frames: frames)
            } else {
                ring.push(ptr0, count: frames, stride: 1)
            }
        }

        semaphore.signal()
    }

    if status != noErr || ioProcID == nil {
        fail("AudioDeviceCreateIOProcIDWithBlock failed (OSStatus \(status)).")
    }

    defer {
        if let proc = ioProcID {
            AudioDeviceStop(aggDeviceID, proc)
            AudioDeviceDestroyIOProcID(aggDeviceID, proc)
        }
    }

    status = AudioDeviceStart(aggDeviceID, ioProcID)
    if status != noErr {
        fail("AudioDeviceStart failed (OSStatus \(status)).")
    }

    var outChunk = [Float](repeating: 0, count: 4096)
    while !stopFlag.get() && !restartFlag.get() {
        _ = semaphore.wait(timeout: .now() + .milliseconds(80))
        while !stopFlag.get() && !restartFlag.get() {
            let n = ring.pop(into: &outChunk)
            if n == 0 {
                break
            }
            let byteCount = n * MemoryLayout<Float>.size
            let ok = outChunk.withUnsafeBytes { rawBuf in
                writeAllFD(STDOUT_FILENO, rawBuf.baseAddress!, byteCount)
            }
            if !ok {
                stopFlag.set(true)
                return false
            }
        }
    }

    return restartFlag.get() && !stopFlag.get()
}

@available(macOS 14.2, *)
func runCapture() {
    signal(SIGPIPE, SIG_IGN)
    signal(SIGINT) { _ in stopFlag.set(true) }
    signal(SIGTERM) { _ in stopFlag.set(true) }

    // Listen for default output device switches (e.g. speakers <-> headphones)
    var defaultOutAddr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultOutputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    let listenerQueue = DispatchQueue(label: "com.musicviz.devicelistener")
    let listenerBlock: AudioObjectPropertyListenerBlock = { _, _ in
        restartFlag.set(true)
    }
    AudioObjectAddPropertyListenerBlock(
        AudioObjectID(kAudioObjectSystemObject),
        &defaultOutAddr,
        listenerQueue,
        listenerBlock
    )
    defer {
        AudioObjectRemovePropertyListenerBlock(
            AudioObjectID(kAudioObjectSystemObject),
            &defaultOutAddr,
            listenerQueue,
            listenerBlock
        )
    }

    var headerSent = false
    while !stopFlag.get() {
        let shouldRestart = runCaptureSession(headerSent: &headerSent)
        if !shouldRestart {
            break
        }
        // Brief settle delay on output device switch
        usleep(150_000)
    }
}

if CommandLine.arguments.contains("--help") || CommandLine.arguments.contains("-h") {
    print("Usage: audio_tap")
    print("Captures macOS system speaker output via CoreAudio Process Tap and streams raw Float32 PCM to stdout.")
    print("Automatically follows default output device changes (e.g. speakers <-> headphones).")
    print("Header line: MVIZ <sample_rate> <channels>")
    exit(0)
}

if #available(macOS 14.2, *) {
    runCapture()
} else {
    fail("CoreAudio Process Tap requires macOS 14.2 or later.")
}
