/* Orbita/Xenon: non-blocking error journal.
 * xc_log() records to RAM; only the existing hw3/menu worker writes FatFs.
 * HANG.TXT remains the separate direct-sector crash/watchdog path.
 */
#include "xc_port.h"
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>

#ifndef XCLOUD360_ERRORLOG_ALL
#define XCLOUD360_ERRORLOG_ALL 0
#endif

#define XE_SLOTS 48
#define XE_WIDTH 196
#define XE_FILE_LIMIT (256u * 1024u)
#define XE_BATCH 12
static char g_lines[XE_SLOTS][XE_WIDTH];
static unsigned g_order[XE_SLOTS];
static unsigned g_head, g_count, g_seq;
static unsigned g_lost, g_lost_written;
static volatile int g_lock;
static uint64_t g_flush_at;

static int lock_try(void) { return __sync_lock_test_and_set(&g_lock, 1) == 0; }
static void unlock(void) { __sync_lock_release(&g_lock); }

static int contains_ci(const char *hay, const char *needle) {
    if (!hay || !needle || !*needle) return 0;
    for (; *hay; hay++) {
        const char *a = hay, *b = needle;
        while (*a && *b && tolower((unsigned char)*a) == tolower((unsigned char)*b)) { a++; b++; }
        if (!*b) return 1;
    }
    return 0;
}

static int is_error(const char *s) {
    static const char *const terms[] = {
        "[wdog]", "[crash]", "[fatal]", "falh", "erro", "error", "timeout",
        "timed out", "trav", "parad", "crash", "fatal", "segmentation",
        "invalid", "inválid", "recus", "lost", "stall", "disconnect",
        "sem rede", "não conect", "nao conect", "corrupt", "not found",
        "could not", "unable", "HTTP 4", "HTTP 5", "rejected",
        "failed", "abort", "panic", "assert", "watchdog", "hang",
        "sem conexão", "sem conex", "sem resposta", "indispon",
        "cancelado", "out of memory"
    };
    for (unsigned i = 0; i < sizeof(terms) / sizeof(terms[0]); ++i)
        if (contains_ci(s, terms[i])) return 1;
    return 0;
}

static const char *category(const char *s) {
    if (contains_ci(s, "[wdog]") || contains_ci(s, "[crash]")) return "CRASH";
    if (contains_ci(s, "[input]") || contains_ci(s, "[pad")) return "INPUT";
    if (contains_ci(s, "[wifi]") || contains_ci(s, "[net]") ||
        contains_ci(s, "[xhs]") || contains_ci(s, "[dns]")) return "NETWORK";
    if (contains_ci(s, "[catalog]") || contains_ci(s, "[cat]")) return "CATALOG";
    if (contains_ci(s, "[login]") || contains_ci(s, "[auth]")) return "LOGIN";
    if (contains_ci(s, "[sess") || contains_ci(s, "[webrtc]") ||
        contains_ci(s, "[game]")) return "SESSION";
    if (contains_ci(s, "[usb]")) return "STORAGE";
    if (contains_ci(s, "[dec]") || contains_ci(s, "[gpu]") ||
        contains_ci(s, "[video]") || contains_ci(s, "[audio]")) return "MEDIA";
    if (contains_ci(s, "[update]")) return "UPDATE";
    return "GENERAL";
}

/* A local journal may be copied from the USB drive: never store credentials. */
static int contains_sensitive(const char *s) {
    static const char *const terms[] = {
        "authorization:", "bearer ", "access_token", "refresh_token",
        "id_token", "password", "client_secret", "token=", "code=",
        "api_key", "x-api-key", "BETAKEY", "secret="
    };
    for (unsigned i = 0; i < sizeof(terms) / sizeof(terms[0]); ++i)
        if (contains_ci(s, terms[i])) return 1;
    return 0;
}

void xc_error_capture(const char *line) {
    if (!line || !*line || contains_ci(line, "ERRORS.TXT") ||
        contains_ci(line, "[errlog]")) return;
    if (!XCLOUD360_ERRORLOG_ALL && !is_error(line)) return;
    char entry[XE_WIDTH];
    memset(entry, 0, sizeof(entry));
    uint64_t ms = xcn_now_ms();
    const char *msg = contains_sensitive(line) ? "[detalhe oculto: credencial]" : line;
    snprintf(entry, sizeof(entry), "ms=%llu [%s] %.139s\n",
             (unsigned long long)ms, category(line), msg);
    if (!lock_try()) { __sync_fetch_and_add(&g_lost, 1); return; }
    if (g_count == XE_SLOTS) {
        g_head = (g_head + 1) % XE_SLOTS;
        g_count--;
        __sync_fetch_and_add(&g_lost, 1);
    }
    unsigned tail = (g_head + g_count) % XE_SLOTS;
    memcpy(g_lines[tail], entry, sizeof(entry));
    /* Number at the beginning identifies each entry, even after overwrite. */
    g_order[tail] = ++g_seq;
    g_count++;
    unlock();
}

/* Only call in the catalog/menu worker (hw3); NEVER in network, decoder or
 * USB interrupt paths. No FatFs operation happens in xc_error_capture(). */
int xc_error_flush_step(void) {
    uint64_t now = xcn_now_ms();
    if (now < g_flush_at) return 0;
    g_flush_at = now + 2000;
    if (!lock_try()) return 0;
    char batch[XE_BATCH * XE_WIDTH + 100];
    size_t n = 0;
    unsigned count = g_count < XE_BATCH ? g_count : XE_BATCH;
    unsigned first = g_head;
    unsigned dropped = __sync_fetch_and_add(&g_lost, 0);
    unsigned before = g_lost_written;
    for (unsigned i = 0; i < count; i++) {
        const char *line = g_lines[(first + i) % XE_SLOTS];
        size_t len = strlen(line);
        if (len > sizeof(batch) - n - 1) break;
        memcpy(batch + n, line, len);
        n += len;
    }
    /* Flush only the entries successfully copied into this batch. */
    unsigned copied = 0;
    size_t scan = 0;
    while (scan < n) { if (batch[scan++] == '\n') copied++; }
    if (dropped != before) {
        int w = snprintf(batch + n, sizeof(batch) - n,
                         "[errlog] RAM overflow/lock contention: total dropped=%u\n", dropped);
        if (w > 0 && (size_t)w < sizeof(batch) - n) n += (size_t)w;
    }
    unsigned last_seq = copied ? g_order[(first + copied - 1) % XE_SLOTS] : 0;
    unlock();
    if (!n) return 0;
    if (xc_store_append("ERRORS.TXT", "ERR_OLD.TXT", batch, n, XE_FILE_LIMIT) != 0) return 0;
    if (!lock_try()) return 1;
    /* New arrivals stay queued; overwritten records must not be dequeued twice. */
    if (copied) while (g_count && (int32_t)(g_order[g_head] - last_seq) <= 0) {
        g_head = (g_head + 1) % XE_SLOTS;
        g_count--;
    }
    if (g_lost_written < dropped) g_lost_written = dropped;
    unlock();
    return 1;
}
