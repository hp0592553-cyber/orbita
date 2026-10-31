/* Local compatibility types for upstream FFmpeg without the Orbita profiler.
 * Mirrors xc_prof.h from deps/ffmpeg-xenon/orbita-ffmpeg.patch.
 * The build uses this only with XCLOUD360_FFMPEG_NO_PROF=1.
 * Counters remain zero; not a substitute for an actual decoder audit.
 */
#ifndef XC360_XC_PROF_COMPAT_H
#define XC360_XC_PROF_COMPAT_H
#include <stdint.h>
enum { XCP_ENTROPY = 0, XCP_RECON, XCP_MC, XCP_DEBLOCK, XCP_AWAIT, XCP_DECODE, XCP_NKIND };
typedef struct {
    volatile uint64_t tb[XCP_NKIND];
    volatile uint32_t frames;
    uint32_t pad[7];
} xc_prof_thr_t;
typedef struct {
    xc_prof_thr_t t[8];
    volatile uint32_t slices, slices_nonref, slices_cabac, slices_idr;
    volatile int profile_idc, level_idc, mb_w, mb_h;
} xc_prof_t;
extern xc_prof_t xc_prof;
extern volatile int xc_prof_on;
#endif
