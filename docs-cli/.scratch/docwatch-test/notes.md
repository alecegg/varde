# Q3 Planning

We estimated Q3 revenue at $377,932 based on 12% monthly growth from a $100k base, see src/math.rs for the calc.

@cx: does src/math.rs use integer division anywhere that could cause rounding drift? Answer only, do not edit code.
@cx-reply: Yes. Each month uses integer division by 100, truncating fractions and causing rounding drift.
