/* CoreMediaIO output-stream producer. No application or libobs ABI. */
#import <Foundation/Foundation.h>
#import <CoreMediaIO/CoreMediaIO.h>
#import <CoreVideo/CoreVideo.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    CMIODeviceID device;
    CMIOStreamID stream;
    CMSimpleQueueRef queue;
    CVPixelBufferPoolRef pool;
    CMVideoFormatDescriptionRef format;
    uint32_t width, height, fps_num, fps_den;
    bool started;
    uint64_t published;
    OSStatus last_error;
} CameraSink;

static void queue_changed(CMIOStreamID stream, void *token, void *context) {
    (void)stream; (void)token; (void)context;
}

static void set_colorimetry(CVPixelBufferRef buffer) {
    CVBufferSetAttachment(buffer, kCVImageBufferYCbCrMatrixKey, kCVImageBufferYCbCrMatrix_ITU_R_709_2,
                          kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(buffer, kCVImageBufferColorPrimariesKey, kCVImageBufferColorPrimaries_ITU_R_709_2,
                          kCVAttachmentMode_ShouldPropagate);
    CVBufferSetAttachment(buffer, kCVImageBufferTransferFunctionKey, kCVImageBufferTransferFunction_ITU_R_709_2,
                          kCVAttachmentMode_ShouldPropagate);
}

static CMIOObjectPropertyAddress property(UInt32 selector) {
    return (CMIOObjectPropertyAddress){selector, kCMIOObjectPropertyScopeGlobal,
                                      kCMIOObjectPropertyElementMain};
}

static OSStatus read_property(CMIOObjectID object, UInt32 selector, UInt32 size, void *value) {
    CMIOObjectPropertyAddress address = property(selector);
    UInt32 used = 0;
    OSStatus status = CMIOObjectGetPropertyData(object, &address, 0, NULL, size, &used, value);
    return status ? status : used == size ? noErr : kCMIOHardwareBadPropertySizeError;
}

static OSStatus find_sink(const char *uid, CameraSink *sink) {
    CMIOObjectPropertyAddress address = property(kCMIOHardwarePropertyDevices);
    UInt32 size = 0, used = 0;
    OSStatus status = CMIOObjectGetPropertyDataSize(kCMIOObjectSystemObject, &address, 0, NULL, &size);
    if (status) return status;
    if (!size) return kCMIOHardwareBadDeviceError;
    CMIOObjectID *devices = calloc(1, size);
    if (!devices) return memFullErr;
    status = CMIOObjectGetPropertyData(kCMIOObjectSystemObject, &address, 0, NULL, size, &used, devices);
    if (status) { free(devices); return status; }
    for (UInt32 index = 0; index < used / sizeof(*devices); index++) {
        CFStringRef candidate = NULL;
        status = read_property(devices[index], kCMIODevicePropertyDeviceUID, sizeof(candidate), &candidate);
        if (status || !candidate) continue;
        bool matches = [(NSString *)candidate isEqualToString:[NSString stringWithUTF8String:uid]];
        CFRelease(candidate);
        if (matches) { sink->device = devices[index]; break; }
    }
    free(devices);
    if (!sink->device) return kCMIOHardwareBadDeviceError;
    address = property(kCMIODevicePropertyStreams);
    status = CMIOObjectGetPropertyDataSize(sink->device, &address, 0, NULL, &size);
    if (status) return status;
    if (!size) return kCMIOHardwareBadStreamError;
    CMIOStreamID *streams = calloc(1, size);
    if (!streams) return memFullErr;
    status = CMIOObjectGetPropertyData(sink->device, &address, 0, NULL, size, &used, streams);
    if (!status) {
        for (UInt32 index = 0; index < used / sizeof(*streams); index++) {
            UInt32 direction = 1;
            if (!read_property(streams[index], kCMIOStreamPropertyDirection, sizeof(direction), &direction)
                && direction == 0) { sink->stream = streams[index]; break; }
        }
    }
    free(streams);
    return status ? status : sink->stream ? noErr : kCMIOHardwareBadStreamError;
}

uint64_t pyc_camera_consumed(CameraSink *sink) {
    if (!sink || !sink->queue) return 0;
    uint64_t pending = CMSimpleQueueGetCount(sink->queue);
    return sink->published > pending ? sink->published - pending : 0;
}

int32_t pyc_camera_error(CameraSink *sink) { return sink ? sink->last_error : paramErr; }

static int rejected(CameraSink *sink, OSStatus status) {
    sink->last_error = status;
    return -1;
}

int32_t pyc_camera_close(CameraSink *sink) {
    if (!sink) return noErr;
    @autoreleasepool {
        OSStatus stopped = sink->started ? CMIODeviceStopStream(sink->device, sink->stream) : noErr;
        OSStatus status = stopped;
        if (sink->queue) {
            CMSimpleQueueRef detached = NULL;
            OSStatus unregistered = CMIOStreamCopyBufferQueue(sink->stream, NULL, NULL, &detached);
            if (!status) status = unregistered;
            if (detached) CFRelease(detached);
            /* A failed stop cannot establish SPSC consumer quiescence. Never
               dequeue concurrently with a driver that may still be running. */
            if (!stopped) {
                const void *sample;
                while ((sample = CMSimpleQueueDequeue(sink->queue))) CFRelease(sample);
            }
            CFRelease(sink->queue);
        }
        if (sink->format) CFRelease(sink->format);
        if (sink->pool) CVPixelBufferPoolRelease(sink->pool);
        free(sink);
        return status;
    }
}

CameraSink *pyc_camera_create(const char *uid, uint32_t width, uint32_t height,
                             uint32_t fps_num, uint32_t fps_den, int32_t *error) {
    if (error) *error = paramErr;
    if (!uid || !*uid || !width || !height || width > 16384 || height > 16384 ||
        width % 2 || height % 2 || !fps_num || !fps_den || fps_num > INT32_MAX || fps_den > INT32_MAX) return NULL;
    @autoreleasepool {
        CameraSink *sink = calloc(1, sizeof(*sink));
        if (!sink) { if (error) *error = memFullErr; return NULL; }
        sink->width = width; sink->height = height;
        sink->fps_num = fps_num; sink->fps_den = fps_den;
        OSStatus status = find_sink(uid, sink);
        if (status) goto failed;
        /* Polling avoids callback contexts whose asynchronous teardown lifetime
           would otherwise depend on an undocumented CMIO unregister barrier. */
        status = CMIOStreamCopyBufferQueue(sink->stream, queue_changed, NULL, &sink->queue);
        if (status || !sink->queue) { if (!status) status = kCMIOHardwareBadStreamError; goto failed; }
        NSDictionary *attributes = @{
            (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
            (id)kCVPixelBufferWidthKey: @(width), (id)kCVPixelBufferHeightKey: @(height),
            (id)kCVPixelBufferIOSurfacePropertiesKey: @{}
        };
        status = CVPixelBufferPoolCreate(kCFAllocatorDefault, NULL,
                                         (CFDictionaryRef)attributes, &sink->pool);
        if (status) goto failed;
        CVPixelBufferRef prototype = NULL;
        status = CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, sink->pool, &prototype);
        if (status) goto failed;
        set_colorimetry(prototype);
        status = CMVideoFormatDescriptionCreateForImageBuffer(kCFAllocatorDefault, prototype, &sink->format);
        CVPixelBufferRelease(prototype);
        if (status) goto failed;
        status = CMIODeviceStartStream(sink->device, sink->stream);
        if (status) goto failed;
        sink->started = true;
        if (error) *error = noErr;
        return sink;
failed:
        if (error) *error = status;
        pyc_camera_close(sink);
        return NULL;
    }
}

/* One caller writes; CoreMediaIO alone drains the bounded stream queue. */
int pyc_camera_write(CameraSink *sink, const uint8_t *y, uint32_t y_stride,
                     const uint8_t *uv, uint32_t uv_stride, uint64_t timestamp) {
    if (!sink) return -1;
    if (!sink->started || !y || !uv || y_stride < sink->width || uv_stride < sink->width)
        return rejected(sink, paramErr);
    @autoreleasepool {
        UInt32 alive = 0;
        OSStatus device_status = read_property(sink->device, kCMIODevicePropertyDeviceIsAlive, sizeof(alive), &alive);
        if (device_status || !alive) return rejected(sink, device_status ? device_status : kCMIOHardwareBadDeviceError);
        if (CMSimpleQueueGetCount(sink->queue) >= CMSimpleQueueGetCapacity(sink->queue)) return 0;
        NSDictionary *limits = @{(id)kCVPixelBufferPoolAllocationThresholdKey: @4};
        CVPixelBufferRef buffer = NULL;
        CVReturn status = CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(
            kCFAllocatorDefault, sink->pool, (CFDictionaryRef)limits, &buffer);
        if (status == kCVReturnWouldExceedAllocationThreshold) return 0;
        if (status) return rejected(sink, status);
        status = CVPixelBufferLockBaseAddress(buffer, 0);
        if (status) { CVPixelBufferRelease(buffer); return rejected(sink, status); }
        const uint8_t *planes[] = {y, uv};
        uint32_t strides[] = {y_stride, uv_stride};
        for (size_t plane = 0; plane < 2; plane++) {
            uint8_t *destination = CVPixelBufferGetBaseAddressOfPlane(buffer, plane);
            size_t stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, plane);
            size_t rows = CVPixelBufferGetHeightOfPlane(buffer, plane);
            for (size_t row = 0; row < rows; row++)
                memcpy(destination + row * stride, planes[plane] + row * strides[plane], sink->width);
        }
        CVPixelBufferUnlockBaseAddress(buffer, 0);
        set_colorimetry(buffer);
        CMSampleTimingInfo timing = {.duration = CMTimeMake(sink->fps_den, sink->fps_num),
            .presentationTimeStamp = CMTimeMake(timestamp, 1000000000), .decodeTimeStamp = kCMTimeInvalid};
        CMSampleBufferRef sample = NULL;
        status = CMSampleBufferCreateForImageBuffer(kCFAllocatorDefault, buffer, true, NULL, NULL,
                                                    sink->format, &timing, &sample);
        CVPixelBufferRelease(buffer);
        if (status) return rejected(sink, status);
        status = CMSimpleQueueEnqueue(sink->queue, sample);
        if (status) CFRelease(sample);
        else sink->published++;
        return status == kCMSimpleQueueError_QueueIsFull ? 0 : status ? rejected(sink, status) : 1;
    }
}
