// Bit-exact integer OFI with EWMA accumulation.
//
// RTL port of src/ofi_signal/ofi_core.py / c/ofi_core.c, per
// ofi_golden_model_spec.md section 4.3 and section 8 ("What maps well").
// One-cycle latency: assert in_valid with a new top-of-book, the
// corresponding (e_n, acc, flags) appears registered on the next posedge,
// with out_valid high. This maps 1:1 onto OFICore.event() being a pure
// function of (prev_state, new_top) -- same mapping the spec calls out.
//
// Written in Verilog-2001 style (reg/wire, always @*) rather than
// SystemVerilog's always_comb/logic -- the Icarus Verilog build available
// when this was authored does not support those SV-2012 constructs even
// with -g2012. Functionally identical either way; port to `logic` if your
// toolchain supports it.
//
// Bit widths here are generous (ACC_WIDTH=64, wide intermediate products)
// rather than tightly sized per the spec's section 4.1 headroom analysis --
// this is a functional/verification target for the cocotb comparison
// against the golden model, not an area/timing-closed synthesis result.

module ofi_core #(
    parameter K_DECAY   = 6,
    parameter THETA_Q16 = 6554,
    parameter ACC_WIDTH = 64
) (
    input                              clk,
    input                              rst_n,

    input                              in_valid,
    input      signed [31:0]           bid_px,
    input      signed [31:0]           bid_qty,
    input      signed [31:0]           ask_px,
    input      signed [31:0]           ask_qty,

    output reg                         out_valid,
    output reg signed [31:0]           e_n,
    output reg signed [ACC_WIDTH-1:0]  acc,
    output reg [1:0]                   flags
);

    // --- registered book-event and accumulator state ---
    reg                        has_prev;
    reg signed [31:0]          prev_bid_px, prev_bid_qty;
    reg signed [31:0]          prev_ask_px, prev_ask_qty;
    reg signed [ACC_WIDTH-1:0] acc_reg;
    reg signed [ACC_WIDTH-1:0] depth_acc_reg;

    // --- combinational OFI event term: 4 compares, 4 conditional adds ---
    reg signed [33:0] e_wide;
    always @* begin
        e_wide = 34'sd0;
        if (bid_px >= prev_bid_px) e_wide = e_wide + bid_qty;
        if (bid_px <= prev_bid_px) e_wide = e_wide - prev_bid_qty;
        if (ask_px <= prev_ask_px) e_wide = e_wide - ask_qty;
        if (ask_px >= prev_ask_px) e_wide = e_wide + prev_ask_qty;
    end

    // --- saturate e_wide to signed 32 bits (spec: sat32) ---
    reg signed [31:0] e_sat;
    always @* begin
        if (e_wide > 34'sh07FFFFFFF)
            e_sat = 32'sh7FFFFFFF;
        else if (e_wide < -34'sh080000000)
            e_sat = -32'sh80000000;
        else
            e_sat = e_wide[31:0];
    end

    // --- EWMA accumulate (one shift, two adds) and depth EWMA ---
    //
    // NOTE: a Verilog concatenation {..} is ALWAYS unsigned by the LRM,
    // regardless of the signedness of its parts. Mixing one into a signed
    // +/- expression makes the whole expression's arithmetic unsigned,
    // which silently turns `>>>` into a logical (not arithmetic) shift on
    // any negative operand sharing that expression -- observed as acc
    // picking up a spurious high bit near position (ACC_WIDTH-K_DECAY)
    // whenever acc_reg was negative. Every sign-extending concatenation
    // below is wrapped in $signed(...) to force it back to a signed type
    // before it participates in signed arithmetic.
    reg signed [ACC_WIDTH-1:0] acc_next, depth_next, d_wide;
    always @* begin
        d_wide     = $signed({{(ACC_WIDTH-32){bid_qty[31]}}, bid_qty}) +
                     $signed({{(ACC_WIDTH-32){ask_qty[31]}}, ask_qty});
        acc_next   = acc_reg - (acc_reg >>> K_DECAY) +
                     $signed({{(ACC_WIDTH-32){e_sat[31]}}, e_sat});
        depth_next = depth_acc_reg - (depth_acc_reg >>> K_DECAY) + d_wide;
    end

    // --- threshold WITHOUT division (spec section 3.2) ---
    reg signed [ACC_WIDTH+16-1:0] lhs;
    reg signed [ACC_WIDTH+32-1:0] theta_ext, depth_ext, theta_mul, rhs_wide;
    reg signed [ACC_WIDTH+16-1:0] rhs;
    always @* begin
        lhs       = $signed({{16{acc_next[ACC_WIDTH-1]}}, acc_next}) <<< 16;
        theta_ext = $signed({{(ACC_WIDTH){1'b0}}, THETA_Q16[31:0]});
        depth_ext = $signed({{32{depth_next[ACC_WIDTH-1]}}, depth_next});
        theta_mul = theta_ext * depth_ext;
        rhs_wide  = theta_mul >>> K_DECAY;
        rhs       = rhs_wide[ACC_WIDTH+16-1:0];
    end

    reg [1:0] flags_comb;
    always @* begin
        flags_comb = 2'b00;
        if (lhs > rhs)  flags_comb[0] = 1'b1; // buy pressure
        if (lhs < -rhs) flags_comb[1] = 1'b1; // sell pressure
    end

    // --- sequential update: one registered pipeline stage, per spec 4.3 ---
    always @(posedge clk) begin
        if (!rst_n) begin
            has_prev      <= 1'b0;
            prev_bid_px   <= 32'sd0;
            prev_bid_qty  <= 32'sd0;
            prev_ask_px   <= 32'sd0;
            prev_ask_qty  <= 32'sd0;
            acc_reg       <= {ACC_WIDTH{1'b0}};
            depth_acc_reg <= {ACC_WIDTH{1'b0}};
            out_valid     <= 1'b0;
            e_n           <= 32'sd0;
            acc           <= {ACC_WIDTH{1'b0}};
            flags         <= 2'b00;
        end
        else if (in_valid) begin
            if (!has_prev) begin
                has_prev      <= 1'b1;
                prev_bid_px   <= bid_px;
                prev_bid_qty  <= bid_qty;
                prev_ask_px   <= ask_px;
                prev_ask_qty  <= ask_qty;
                depth_acc_reg <= d_wide <<< K_DECAY;
                acc_reg       <= {ACC_WIDTH{1'b0}};
                out_valid     <= 1'b1;
                e_n           <= 32'sd0;
                acc           <= {ACC_WIDTH{1'b0}};
                flags         <= 2'b00;
            end
            else begin
                prev_bid_px   <= bid_px;
                prev_bid_qty  <= bid_qty;
                prev_ask_px   <= ask_px;
                prev_ask_qty  <= ask_qty;
                acc_reg       <= acc_next;
                depth_acc_reg <= depth_next;
                out_valid     <= 1'b1;
                e_n           <= e_sat;
                acc           <= acc_next;
                flags         <= flags_comb;
            end
        end
        else begin
            out_valid <= 1'b0;
        end
    end

endmodule
