# Beam Designer

## Purpose and limitations

Provide educational beam analysis and preliminary strength and stiffness
screening for a single beam. Results are not a complete code-compliant design
or a substitute for review by a qualified engineer.

The app does not check continuous beams, buckling, or other design limit states.
A passing result applies only to the checks described here.

## V1 scope

- One simply supported beam or one cantilever.
- Steel W-shapes only. Lumber is not included in v1.
- Multiple vertical point loads and uniform loads, including loads over only
  part of the span.
- No applied couples or moving loads.
- Exclude beam self-weight.

## Inputs and units

- Support condition and positive span, entered in feet.
- Steel W-shape designation selected from a section-property table.
- Point-load magnitude and position, and uniform-load magnitude and start/end
  positions. Positions are measured from the left support for a simply
  supported beam and from the fixed end for a cantilever.
- Load direction for each load.
- Allowable bending stress, entered by the user in ksi.

Require point loads to lie on the beam and uniform-load intervals to satisfy
0 <= start < end <= span. The allowable bending stress must be positive.

Use US customary units: span in feet, point loads in kips, uniform loads in
kips per foot, stress in ksi, and deflection in inches. Convert consistently
for calculations. The section-property table must document its source and
provide at least the strong-axis moment of inertia Ix and section modulus Sx.
Use E = 29,000 ksi for steel.

Treat entered loads as service-level loads. Do not add load combinations or
self-weight.

## Calculations and checks

- Calculate support reactions, shear, and bending moment using statics.
- Calculate the elastic deflection curve and its maximum absolute value.
- Calculate maximum absolute elastic bending stress as fb = |Mmax| / Sx,
  converting moment to kip-inches for the stress calculation.
- The bending check passes when fb is less than or equal to the user-entered
  allowable bending stress. If no allowable stress is entered, show bending as
  not evaluated, not as a pass.
- The deflection check passes when maximum absolute deflection is less than or
  equal to L/360, where L is the support-to-support span. Apply this check to
  the entered service-level loads.

Use and display a consistent sign convention for loads, reactions, shear,
moment, and deflection.

## Outputs

- A beam diagram showing its supports and applied loads.
- Shear, moment, and deflection diagrams.
- Support reactions, maximum shear, maximum moment, maximum deflection, and
  the deflection limit.
- Pass/fail status for each evaluated check; show the calculated value and
  comparison limit. Identify checks that were not evaluated.

## Look and feel

Use a clean, professional presentation. Open with the validation example
below loaded. The example must identify its assumptions; do not imply that
the bending check passed unless an allowable stress has been supplied.

## Validation

Use W12x26 with Ix = 204 in^4 and E = 29,000 ksi for these hand checks.
Exclude self-weight. Round displayed values to three significant digits.

1. **Simply supported, uniform load:** L = 20 ft, w = 1 kip/ft over the full
   span. Expected reactions are 10.0 kip each, maximum moment is 50.0 kip-ft,
   and maximum deflection is 0.609 in. The L/360 limit is 0.667 in, so the
   deflection check passes.
2. **Simply supported, midspan point load:** L = 20 ft, P = 10 kip.
   Expected reactions are 5.00 kip each, maximum moment is 50.0 kip-ft,
   maximum deflection is 0.487 in, and the L/360 limit is 0.667 in.
3. **Cantilever, end point load:** L = 10 ft, P = 1 kip at the free end.
   Expected support reaction is 1.00 kip, fixed-end moment magnitude is
   10.0 kip-ft, maximum deflection is 0.0974 in, and the L/360 limit is
   0.333 in.
4. **Zero load:** For either support condition, all reactions, shear, moment,
   and deflection are zero.

## Out of scope

- Continuous beams and multiple spans.
- Buckling and other design limit states.
- Lumber.
- Code-compliant member design or load combinations.
