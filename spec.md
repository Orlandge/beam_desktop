# Beam Designer

## Purpose and limitations

Provide educational beam analysis and preliminary strength and stiffness
screening for a single beam. Results are not a complete code-compliant design
or a substitute for review by a qualified engineer.

The app does not check continuous beams, buckling, or other design limit states.
A passing result applies only to the checks described here.

## Desktop application

- Implement the app in Python with Tkinter for the desktop interface.
- Use Matplotlib for the beam, shear, moment, and deflection diagrams.
- Use NumPy for numerical calculations and plotting support where appropriate.
- Start the app from this folder with `python app.py` (or `python3 app.py`).
- Use `index.html` as the behavioral and visual reference.
- Open with the validation example loaded and analysis results visible.
- Keep calculation logic separate from the Tkinter interface so it can be
  tested without opening a window.

## Analysis scope

- One simply supported beam or one cantilever.
- Steel W-shapes only. Lumber is not included.
- Multiple vertical point loads and uniform loads, including loads over only
  part of the span.
- No applied couples or moving loads.
- Exclude beam self-weight.

## Inputs and units

- Support condition and positive span, entered in feet.
- Steel W-shape designation selected from a limited section-property table.
- Point-load magnitude and position, and uniform-load magnitude and start/end
  positions. Positions are measured from the left support for a simply
  supported beam and from the fixed end for a cantilever.
- Load direction for each load.
- Optional allowable bending stress, entered in ksi.

Require point loads to lie on the beam and uniform-load intervals to satisfy
`0 <= start < end <= span`. Load magnitudes must be nonnegative. The allowable
bending stress must be positive when supplied; if left blank, bending is not
evaluated.

Use US customary units: span and load positions in feet, point loads in kips,
uniform loads in kips per foot, stress in ksi, and deflection in inches.
Convert consistently for calculations. The section-property table must
document its source and provide at least strong-axis moment of inertia `Ix`
and section modulus `Sx`. Use `E = 29,000 ksi` for steel.

Treat entered loads as service-level loads. Do not add load combinations or
self-weight.

## Calculations and checks

- Calculate support reactions, shear, and bending moment using statics.
- Calculate the elastic deflection curve and its maximum absolute value.
- Calculate maximum absolute elastic bending stress as
  `fb = |Mmax| / Sx`, converting moment to kip-inches for the stress
  calculation.
- The bending check passes when `fb` is less than or equal to the
  user-entered allowable bending stress. If no allowable stress is entered,
  show bending as not evaluated, not as a pass.
- The deflection check passes when maximum absolute deflection is less than
  or equal to `L/360`, where `L` is the support-to-support span. Apply this
  check to the entered service-level loads.

Use a consistent sign convention: downward applied loads and deflection are
positive; upward reactions are positive; positive bending moment is sagging.
Label quantities and units in the interface and exported results.

## Main window

- Present beam/support/span/section/allowable inputs and editable point- and
  uniform-load lists.
- Provide controls to add and remove loads, load the validation example, and
  update the analysis.
- Show clear validation errors without replacing the last valid analysis with
  misleading results.
- Display support reactions, maximum shear, maximum moment, maximum
  deflection, deflection limit, bending stress, and pass/fail/not-evaluated
  statuses.
- Draw a beam/load diagram and shear, moment, and deflection diagrams.
- Use a clean, professional layout; round displayed measurements to three
  significant digits.
- Include the educational-use limitation and the source of section properties.

## Desktop file features

### Save and open

Provide **Save** and **Open** commands in a **File** menu. Save and reopen the
support condition, span, section, allowable bending stress, and all point and
uniform loads, including directions and positions. Use a documented,
versioned, human-readable JSON file format. Reject malformed or unsupported
files with a clear error; do not partially replace the current design.

### Export results

Provide a button to save a CSV file that opens in spreadsheet software. Include
the beam length and sampled values along the beam with columns for `x_ft`,
`V_kip`, `M_kip_ft`, and `deflection_in`. Include beam ends and load locations
in the exported samples.

### Calculation sheet

Provide a button to save a PDF calculation sheet suitable for review. List the
beam inputs at the top, show reactions and bending/deflection checks, and
include the beam/load diagram plus shear, moment, and deflection diagrams.
Use readable labels, units, and a clear educational-use limitation.

## Validation

Use W12x26 with `Ix = 204 in^4`, `Sx = 33.4 in^3`, and `E = 29,000 ksi` for
these hand checks. Exclude self-weight. Round displayed values to three
significant digits.

1. **Simply supported, uniform load:** `L = 20 ft`, `w = 1 kip/ft` over the
   full span. Expected reactions are `10.0 kip` each, maximum moment is
   `50.0 kip-ft`, and maximum deflection is `0.609 in`. The `L/360` limit is
   `0.667 in`, so the deflection check passes.
2. **Simply supported, midspan point load:** `L = 20 ft`, `P = 10 kip`.
   Expected reactions are `5.00 kip` each, maximum moment is `50.0 kip-ft`,
   maximum deflection is `0.487 in`, and the `L/360` limit is `0.667 in`.
3. **Cantilever, end point load:** `L = 10 ft`, `P = 1 kip` at the free end.
   Expected support reaction is `1.00 kip`, fixed-end moment magnitude is
   `10.0 kip-ft`, maximum deflection is `0.0974 in`, and the `L/360` limit is
   `0.333 in`.
4. **Zero load:** For either support condition, all reactions, shear, moment,
   and deflection are zero.

Focused automated tests must exercise these calculation cases and the
save/open, CSV, and PDF workflows.

## Section-property source

The initial limited section list and rounded properties are taken from the
AISC Shapes Database values represented in the supplied `index.html`.
Included sections: W8x10 (`Ix = 30.8 in^4`, `Sx = 7.81 in^3`), W10x12
(`53.8`, `10.9`), W12x26 (`204`, `33.4`), W14x22 (`199`, `29.0`),
W16x26 (`301`, `38.4`), and W18x35 (`510`, `57.6`). This is not the full
catalog; verify section data independently before use.

## Out of scope

- Continuous beams and multiple spans.
- Buckling and other design limit states.
- Lumber.
- Code-compliant member design or load combinations.
