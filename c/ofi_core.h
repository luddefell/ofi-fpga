/* Bit-exact integer OFI with EWMA accumulation. C port of
 * src/ofi_signal/ofi_core.py, which is itself the reference implementation
 * from ofi_golden_model_spec.md section 4.3. This header/impl must match
 * the Python model and the RTL cycle-for-cycle -- do not "improve" the
 * arithmetic here without updating both other legs of the spec's
 * three-stage verification flow (section 5).
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    int32_t bid_px;  /* ticks */
    int32_t bid_qty; /* shares */
    int32_t ask_px;
    int32_t ask_qty;
} ofi_top_t;

typedef struct {
    unsigned k;         /* EWMA decay shift: acc -= acc >> k */
    uint32_t theta_q16; /* Q16.16 threshold multiplier */

    bool has_prev;
    ofi_top_t prev;
    int64_t acc;       /* int48 in RTL headroom terms; int64 here per spec 4.1 */
    int64_t depth_acc; /* running depth EWMA */
} ofi_core_t;

typedef struct {
    int32_t e_n;
    int64_t acc;
    uint8_t flags; /* bit0 = buy pressure, bit1 = sell pressure */
} ofi_result_t;

int32_t ofi_sat32(int64_t x);

void ofi_core_init(ofi_core_t *core, unsigned k_decay, uint32_t theta_q16);

/* Process one book state. Mirrors OFICore.event() in ofi_core.py exactly,
 * including returning (0, 0, 0) on the first call (seed, not a signal). */
ofi_result_t ofi_core_event(ofi_core_t *core, ofi_top_t t);
