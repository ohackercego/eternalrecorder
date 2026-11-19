/* Cocoa presentation and bounded IOSurface delivery. No Python or libobs ABI. */
#import <Cocoa/Cocoa.h>
#import <IOSurface/IOSurface.h>
#import <OpenGL/OpenGL.h>
#import <OpenGL/gl3.h>
#import <OpenGL/CGLIOSurface.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <servers/bootstrap.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define SLOT_COUNT 3
#define FRAME_ID 0x50595346
#define ACK_ID 0x50595341

typedef struct {
    mach_msg_header_t header;
    mach_msg_body_t body;
    mach_msg_port_descriptor_t surface, acknowledgement;
    uint64_t sequence;
    uint64_t rendered_at_ns;
    uint32_t slot, width, height;
} Frame;
typedef struct {
    mach_msg_header_t header;
    uint64_t sequence;
    uint32_t slot;
} Ack;
typedef struct {
    IOSurfaceRef surface;
    GLuint texture, framebuffer;
    uint64_t sequence;
    bool busy;
} Slot;
typedef struct {
    mach_port_t destination, acknowledgements;
    uint32_t width, height;
    uint64_t sequence;
    Slot slots[SLOT_COUNT];
} Producer;

@interface PYSurfaceView : NSOpenGLView
@end
@implementation PYSurfaceView
- (NSView *)hitTest:(NSPoint)point { (void)point; return nil; }
@end
typedef struct {
    mach_port_t receive;
    char name[BOOTSTRAP_MAX_NAME_LEN];
    PYSurfaceView *view;
    uint64_t sequence;
    uint64_t latency_ns;
} Presenter;

uint64_t pys_clock_ns(void) {
    mach_timebase_info_data_t scale;
    mach_timebase_info(&scale);
    uint64_t ticks = mach_absolute_time();
    return (ticks / scale.denom) * scale.numer +
           (ticks % scale.denom) * scale.numer / scale.denom;
}

uint64_t pys_presenter_latency_ns(Presenter *presenter) {
    return presenter ? presenter->latency_ns : 0;
}

static void drop_right(mach_port_t port) {
    if (MACH_PORT_VALID(port)) mach_port_deallocate(mach_task_self(), port);
}
static void acknowledge(Frame *frame) {
    Ack ack = {0};
    ack.header.msgh_bits = MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND, 0);
    ack.header.msgh_remote_port = frame->acknowledgement.name;
    ack.header.msgh_size = sizeof(ack);
    ack.header.msgh_id = ACK_ID;
    ack.sequence = frame->sequence;
    ack.slot = frame->slot;
    mach_msg(&ack.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT, sizeof(ack), 0,
             MACH_PORT_NULL, 0, MACH_PORT_NULL);
    mach_msg_destroy(&frame->header);
}

/* Invoked with the producer's graphics context current. Restore all GL bindings. */
static bool create_slot(Slot *slot, uint32_t width, uint32_t height) {
    @autoreleasepool {
    NSDictionary *attributes = @{
        (NSString *)kIOSurfaceWidth: @(width), (NSString *)kIOSurfaceHeight: @(height),
        (NSString *)kIOSurfaceBytesPerElement: @4,
        (NSString *)kIOSurfacePixelFormat: @((uint32_t)0x42475241)
    };
    slot->surface = IOSurfaceCreate((CFDictionaryRef)attributes);
    if (!slot->surface) return false;
    GLint previousTexture, previousRead, previousDraw;
    glGetIntegerv(GL_TEXTURE_BINDING_RECTANGLE, &previousTexture);
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previousRead);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previousDraw);
    glGenTextures(1, &slot->texture);
    glBindTexture(GL_TEXTURE_RECTANGLE, slot->texture);
    CGLError error = CGLTexImageIOSurface2D(CGLGetCurrentContext(), GL_TEXTURE_RECTANGLE,
        GL_RGBA8, width, height, GL_BGRA, GL_UNSIGNED_INT_8_8_8_8_REV, slot->surface, 0);
    glGenFramebuffers(1, &slot->framebuffer);
    glBindFramebuffer(GL_FRAMEBUFFER, slot->framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE,
                           slot->texture, 0);
    bool valid = error == kCGLNoError &&
        glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindTexture(GL_TEXTURE_RECTANGLE, previousTexture);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, previousRead);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previousDraw);
    return valid;
    }
}

void pys_producer_close(Producer *producer) {
    if (!producer) return;
    for (int i = 0; i < SLOT_COUNT; i++) {
        Slot *slot = &producer->slots[i];
        if (slot->framebuffer) glDeleteFramebuffers(1, &slot->framebuffer);
        if (slot->texture) glDeleteTextures(1, &slot->texture);
        if (slot->surface) CFRelease(slot->surface);
    }
    drop_right(producer->destination);
    if (MACH_PORT_VALID(producer->acknowledgements))
        mach_port_destroy(mach_task_self(), producer->acknowledgements);
    free(producer);
}

Producer *pys_producer_create(const char *endpoint, uint32_t width, uint32_t height) {
    if (!endpoint || !width || !height || width > 16384 || height > 16384 ||
        !CGLGetCurrentContext()) return NULL;
    Producer *producer = calloc(1, sizeof(*producer));
    if (!producer) return NULL;
    producer->width = width; producer->height = height;
    kern_return_t result = bootstrap_look_up(bootstrap_port, endpoint, &producer->destination);
    if (result != KERN_SUCCESS) goto failed;
    result = mach_port_allocate(mach_task_self(), MACH_PORT_RIGHT_RECEIVE, &producer->acknowledgements);
    if (result != KERN_SUCCESS) goto failed;
    result = mach_port_insert_right(mach_task_self(), producer->acknowledgements,
                                    producer->acknowledgements, MACH_MSG_TYPE_MAKE_SEND);
    if (result != KERN_SUCCESS) goto failed;
    for (int i = 0; i < SLOT_COUNT; i++)
        if (!create_slot(&producer->slots[i], width, height)) goto failed;
    return producer;
failed:
    pys_producer_close(producer);
    return NULL;
}

/* 1=published, 0=consumer busy, -1=disconnected/invalid graphics. */
int pys_producer_publish(Producer *producer, GLuint texture, GLenum target, uint64_t rendered_at_ns) {
    if (!producer || !CGLGetCurrentContext() || !texture) return -1;
    mach_port_type_t portType;
    if (mach_port_type(mach_task_self(), producer->destination, &portType) != KERN_SUCCESS ||
        (portType & MACH_PORT_TYPE_DEAD_NAME)) return -1;
    for (;;) {
        union { Ack message; char storage[sizeof(Ack) + MAX_TRAILER_SIZE]; } buffer = {0};
        mach_msg_return_t result = mach_msg(&buffer.message.header, MACH_RCV_MSG | MACH_RCV_TIMEOUT,
            0, sizeof(buffer), producer->acknowledgements, 0, MACH_PORT_NULL);
        if (result != MACH_MSG_SUCCESS) break;
        Ack *ack = &buffer.message;
        if (ack->header.msgh_id == ACK_ID && ack->header.msgh_size == sizeof(Ack) &&
            !(ack->header.msgh_bits & MACH_MSGH_BITS_COMPLEX) && ack->slot < SLOT_COUNT) {
            Slot *slot = &producer->slots[ack->slot];
            if (ack->sequence == slot->sequence) slot->busy = false;
        }
        mach_msg_destroy(&ack->header);
    }
    int index = 0;
    while (index < SLOT_COUNT && producer->slots[index].busy) index++;
    if (index == SLOT_COUNT) return 0;
    Slot *slot = &producer->slots[index];
    GLint previousRead, previousDraw;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previousRead);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &previousDraw);
    GLuint read;
    glGenFramebuffers(1, &read);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
    glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, target, texture, 0);
    bool valid = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    GLboolean scissored = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);
    if (valid) {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, slot->framebuffer);
        glBlitFramebuffer(0, 0, producer->width, producer->height,
                         0, producer->height, producer->width, 0, GL_COLOR_BUFFER_BIT, GL_NEAREST);
        /* Cross-process GL sync objects are not shared. Complete writes before publishing. */
        glFinish();
    }
    if (scissored) glEnable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, previousRead);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previousDraw);
    glDeleteFramebuffers(1, &read);
    if (!valid) return -1;
    Frame frame = {0};
    frame.header.msgh_bits = MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND, 0) | MACH_MSGH_BITS_COMPLEX;
    frame.header.msgh_size = sizeof(frame);
    frame.header.msgh_remote_port = producer->destination;
    frame.header.msgh_id = FRAME_ID;
    frame.body.msgh_descriptor_count = 2;
    mach_port_t surfacePort = IOSurfaceCreateMachPort(slot->surface);
    if (!MACH_PORT_VALID(surfacePort)) return -1;
    frame.surface = (mach_msg_port_descriptor_t){.name=surfacePort,
        .disposition=MACH_MSG_TYPE_COPY_SEND, .type=MACH_MSG_PORT_DESCRIPTOR};
    frame.acknowledgement = (mach_msg_port_descriptor_t){.name=producer->acknowledgements,
        .disposition=MACH_MSG_TYPE_COPY_SEND, .type=MACH_MSG_PORT_DESCRIPTOR};
    frame.slot = index; frame.width = producer->width; frame.height = producer->height;
    frame.sequence = ++producer->sequence;
    frame.rendered_at_ns = rendered_at_ns;
    mach_msg_return_t result = mach_msg(&frame.header, MACH_SEND_MSG | MACH_SEND_TIMEOUT,
        sizeof(frame), 0, MACH_PORT_NULL, 0, MACH_PORT_NULL);
    drop_right(surfacePort);
    if (result != MACH_MSG_SUCCESS) return result == MACH_SEND_TIMED_OUT ? 0 : -1;
    slot->sequence = frame.sequence; slot->busy = true;
    return 1;
}

void pys_presenter_close(Presenter *presenter) {
    if (!presenter) return;
    if (presenter->name[0]) {
        kern_return_t ignored = bootstrap_register(bootstrap_port, presenter->name, MACH_PORT_NULL);
        (void)ignored;
    }
    if (MACH_PORT_VALID(presenter->receive))
        mach_port_destroy(mach_task_self(), presenter->receive);
    [presenter->view removeFromSuperview];
    [presenter->view release];
    free(presenter);
}

Presenter *pys_presenter_create(void *parentView, const char *endpoint) {
    if (![NSThread isMainThread] || !parentView || !endpoint ||
        strlen(endpoint) >= BOOTSTRAP_MAX_NAME_LEN) return NULL;
    Presenter *presenter = calloc(1, sizeof(*presenter));
    if (!presenter) return NULL;
    mach_port_t port;
    if (mach_port_allocate(mach_task_self(), MACH_PORT_RIGHT_RECEIVE, &port) != KERN_SUCCESS)
        goto failed;
    presenter->receive = port;
    if (mach_port_insert_right(mach_task_self(), port, port, MACH_MSG_TYPE_MAKE_SEND) != KERN_SUCCESS)
        goto failed;
    char service[BOOTSTRAP_MAX_NAME_LEN];
    strlcpy(service, endpoint, sizeof(service));
    kern_return_t registered = bootstrap_register(bootstrap_port, service, port);
    mach_port_mod_refs(mach_task_self(), port, MACH_PORT_RIGHT_SEND, -1);
    if (registered != KERN_SUCCESS) goto failed;
    strlcpy(presenter->name, endpoint, sizeof(presenter->name));
    NSOpenGLPixelFormatAttribute attributes[] = {NSOpenGLPFADoubleBuffer,
        NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion3_2Core, 0};
    NSOpenGLPixelFormat *format = [[NSOpenGLPixelFormat alloc] initWithAttributes:attributes];
    if (!format) goto failed;
    NSView *parent = (NSView *)parentView;
    presenter->view = [[PYSurfaceView alloc] initWithFrame:parent.bounds pixelFormat:format];
    [format release];
    if (!presenter->view || !presenter->view.openGLContext) goto failed;
    presenter->view.wantsBestResolutionOpenGLSurface = YES;
    presenter->view.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    [parent addSubview:presenter->view];
    return presenter;
failed:
    pys_presenter_close(presenter);
    return NULL;
}

/* Called on the main thread. Draw only the latest queued complete frame. */
int pys_presenter_poll(Presenter *presenter) {
    if (!presenter || ![NSThread isMainThread]) return -1;
    Frame latest = {0}; bool found = false;
    for (int i = 0; i < SLOT_COUNT; i++) {
        union { Frame message; char storage[sizeof(Frame) + MAX_TRAILER_SIZE]; } buffer = {0};
        mach_msg_return_t result = mach_msg(&buffer.message.header, MACH_RCV_MSG | MACH_RCV_TIMEOUT,
            0, sizeof(buffer), presenter->receive, 0, MACH_PORT_NULL);
        if (result == MACH_RCV_TIMED_OUT) break;
        if (result != MACH_MSG_SUCCESS) {
            if (found) acknowledge(&latest);
            return -1;
        }
        Frame *frame = &buffer.message;
        if (frame->header.msgh_id != FRAME_ID || frame->header.msgh_size != sizeof(Frame) ||
            !(frame->header.msgh_bits & MACH_MSGH_BITS_COMPLEX) || frame->body.msgh_descriptor_count != 2 ||
            frame->surface.type != MACH_MSG_PORT_DESCRIPTOR || frame->acknowledgement.type != MACH_MSG_PORT_DESCRIPTOR ||
            !frame->width || !frame->height || frame->width > 16384 || frame->height > 16384) {
            mach_msg_destroy(&frame->header); continue;
        }
        if (found) acknowledge(&latest);
        latest = *frame; found = true;
    }
    if (!found) return 0;
    IOSurfaceRef surface = IOSurfaceLookupFromMachPort(latest.surface.name);
    int status = -1;
    if (!surface || IOSurfaceGetWidth(surface) != latest.width ||
        IOSurfaceGetHeight(surface) != latest.height ||
        IOSurfaceGetPixelFormat(surface) != 0x42475241) goto done;
    NSOpenGLContext *previous = [NSOpenGLContext currentContext];
    NSOpenGLContext *context = presenter->view.openGLContext;
    [context makeCurrentContext];
    [context update];
    GLuint texture, framebuffer;
    glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_RECTANGLE, texture);
    CGLError error = CGLTexImageIOSurface2D(context.CGLContextObj, GL_TEXTURE_RECTANGLE,
        GL_RGBA8, latest.width, latest.height, GL_BGRA, GL_UNSIGNED_INT_8_8_8_8_REV, surface, 0);
    glGenFramebuffers(1, &framebuffer); glBindFramebuffer(GL_READ_FRAMEBUFFER, framebuffer);
    glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_RECTANGLE, texture, 0);
    if (error == kCGLNoError && glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE) {
        NSRect backing = [presenter->view convertRectToBacking:presenter->view.bounds];
        GLsizei width = MAX(1, (GLsizei)backing.size.width), height = MAX(1, (GLsizei)backing.size.height);
        double scale = MIN((double)width / latest.width, (double)height / latest.height);
        GLint drawnWidth = (GLint)(latest.width * scale), drawnHeight = (GLint)(latest.height * scale);
        GLint x = (width - drawnWidth) / 2, y = (height - drawnHeight) / 2;
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glViewport(0, 0, width, height); glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
        glBlitFramebuffer(0, 0, latest.width, latest.height, x, y, x + drawnWidth, y + drawnHeight,
                          GL_COLOR_BUFFER_BIT, GL_LINEAR);
        [context flushBuffer]; glFinish();
        presenter->sequence = latest.sequence; status = 1;
        uint64_t completed = pys_clock_ns();
        presenter->latency_ns = completed >= latest.rendered_at_ns ? completed - latest.rendered_at_ns : 0;
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0); glBindTexture(GL_TEXTURE_RECTANGLE, 0);
    glDeleteFramebuffers(1, &framebuffer); glDeleteTextures(1, &texture);
    [NSOpenGLContext clearCurrentContext]; [previous makeCurrentContext];
done:
    if (surface) CFRelease(surface);
    acknowledge(&latest);
    return status;
}
