# Algorithm specification

Implementation independent description of the calculation core, sufficient to rewrite it in C++ or C#
for the Level 2 system. The Python code under `src/hsmpace/core/` is the reference implementation and
uses standard arithmetic only: no numerical library, no global state, no dependency on Excel or Plotly.

Units: metres, seconds, m/s and m/s2 for motion; millimetres for thicknesses and widths.

## 1. Representation of motion

Each extremity of a piece is described by a contiguous sequence of uniformly accelerated segments:

```
Segment { t0, t1, x0, v0, a }
x(t) = x0 + v0*(t - t0) + 0.5*a*(t - t0)^2
v(t) = v0 + a*(t - t0)
```

Position is continuous between consecutive segments; velocity may be discontinuous, which is
physically correct at bites and tail-outs. There is no integration step: trajectories are exact.

Crossing of a position: solve `0.5*a*tau^2 + v0*tau + (x0 - X) = 0` and discard the roots outside
`[t0, t1]` and those whose velocity sign differs from the one required. With `a = 0` the root is
`tau = (X - x0)/v0`, and with `v0 = 0` there is no crossing.

## 2. State of a piece

```
t            current time
x_head       position of the material head, always >= x_tail
x_tail       position of the material tail
direction    +1 forward, -1 backward
v_lead       magnitude of the speed of the extremity leading in the current direction
lam          product of the lambdas of the engaged passes, initially 1
engaged      list of engaged passes, each with the position of its stand
next_pass    index of the next pass to engage
target       target speed of the leading extremity
zoom_factor  cumulated zoom rolling multiplier, initially 1
ramp_accel   acceleration of the ramp under way, when the event declares its own
stand_accel  acceleration of the stand that bit last
armed        identifier of the event whose ramp is under way, if any
deferred     section event postponed to disengagement, if any
reversing    true while heading for the reversal stop
coiler_brake true once the final slowdown towards the coiler has started
```

Leading and trailing extremity:

```
direction = +1  ->  leading = head,  trailing = tail
direction = -1  ->  leading = tail,  trailing = head
```

Signed velocities and accelerations:

```
v_leading    = direction * v_lead
v_trailing   = direction * v_lead / lam
a_leading    = direction * a_lead
a_trailing   = direction * a_lead / lam
```

where `a_lead` is `+accel` when `target > v_lead`, `-accel` when `target < v_lead`, and 0 otherwise,
and `target` is `nominal_target * zoom_factor`.

The acceleration in force follows one precedence, evaluated at every iteration:

```
accel = ramp_accel            if a ramp declaring its own acceleration is under way
      = stand_accel           else, while at least one pass is engaged
      = section acceleration  else, from the section holding the leading extremity
      = table_accel           else, the global default from the settings
```

Acceleration is therefore read from the layout only on stand rows, where it governs the piece while it
is gripped, and on the coiler row, where it governs the final slowdown (as `ramp_accel = a_c * lam`,
including while the mill is still rolling).

The `lambda` of a pass is `(h_in * w_in) / (h_out * w_out)`. Length grows by itself, because the
extremity downstream of every engaged stand is faster than the upstream one; it must not be imposed.

## 3. Initialisation

* `t = t_release`, `x_head = x_start`, `x_tail = x_start - slab_length`, `direction = +1`,
  `v_lead = 0`, `lam = 1`, `zoom_factor = 1`
* `nominal_target` = approach speed of the first pass, that is the `approach_v` field when present,
  otherwise `v_exit / lambda` of the first pass
* `accel` = acceleration of the starting equipment

## 4. Event loop

At every iteration the acceleration is constant, so all crossings are solved in closed form. The
candidates are computed, the nearest in time is taken, the two segments up to that instant are emitted
and the event is applied.

Candidates:

1. **end of ramp**: `t + (target - v_lead) / a_lead`, when `a_lead != 0`
2. **bite** of the next pass: crossing of the stand position by the leading extremity, in the direction
   of the pass. Only when the direction of the pass matches the current one, no reversal is in
   progress, and the stand is **still ahead**: `direction * (x_stand - x_leading) > tolerance`.
   Without that last condition, right after a bite the leading extremity sits exactly on the stand and
   a second pass on the same stand would bite at the very same instant.
3. **tail-out** of every engaged pass: crossing of the stand position by the trailing extremity
4. **arming of a speed event**, see below
5. **speed event**: crossing of the trigger position by the leading extremity, in the direction
   declared by the event. An event does not re-arm at the same instant at which it fired; section
   events are ignored while a reversal is in progress.
6. **braking point** of a reversal, see below
7. **braking point** of the final slowdown towards the coiler, see below
8. **end of run**: crossing of the coiler position by the trailing extremity, only once no pass is
   left and no stand is engaged

If no candidate exists the simulation is ill posed: when passes are left, the next one is not
reachable in the direction given; otherwise a speed command is missing at the end of the route. Either
way it terminates with an explicit error, never with an infinite loop.

### Applying the events

**End of ramp**: `v_lead = target`. If braking towards a reversal and the target was zero, the piece is
at rest: the wait for the `reversing_delay` of the next pass begins.

**Bite** of pass `p`:

```
lam     = lam * lambda(p)
v_lead  = v_lead * lambda(p)      // the trailing extremity stays continuous
engaged = engaged + p
nominal_target = v_exit(p)
accel   = acceleration of the stand
```

If the pass defines a zoom, a relative speed event is registered with trigger at
`x_stand + zoom_trigger`, forward direction, valid while rolling as well.

**Tail-out** of pass `p`:

```
lam = lam / lambda(p)             // the leading extremity stays continuous
engaged = engaged - p
```

If nothing is left engaged: the deferred event, if any, is applied; then, when the next pass has the
opposite direction, the reversal begins with `zoom_factor = 1`, the acceleration of the stand just
released, and stop point

```
x_stop = x_stand + direction * reversing_clearance
```

where `reversing_clearance` and `reversing_delay` belong to the pass **just completed**, because they
describe the reversal that follows it. At tail-out the trailing extremity sits exactly on the stand, so
the clearance is measured from there. The approach speed used after the wait belongs instead to the
pass being approached.

**Targeted braking.** While braking has not started yet, at every iteration the braking distance
`d = v^2 / (2a)` is computed together with the point at which braking must begin,
`x_brake = x_stop - direction * d`. If the trailing extremity has not reached it yet a crossing
candidate is added; if it has already passed it, braking starts immediately and, when the requested
clearance is greater than zero, the achieved clearance is reported as larger than the requested one.
With a zero clearance the request is "stop as soon as possible" and there is nothing to report.

After tail-out the body is rigid, `lam = 1`, so both extremities translate together and the braking
distance is the same for either of them.

**Speed event**: if stands are engaged and the event is not marked valid while rolling, it is set aside
as deferred, the last one arriving replacing the previous. Otherwise, a relative event multiplies
`zoom_factor` and an absolute one assigns `nominal_target` and resets `zoom_factor` to 1.

### Anticipated ramps

The distance written for a speed event is the position where the target must be **reached**, not where
the ramp begins. Only the nearest event ahead in the current direction is armed, and it is armed at the
instant when the distance still to run equals the distance the ramp needs:

```
remaining(t) = direction * (x_trigger - x_leading(t))
required(t)  = |v_target^2 - v_leading(t)^2| / (2 * a_ramp)
```

Both sides are quadratic in time, so the arming instant is a root of a quadratic and is exact. With
`sigma = +1` when decelerating and `-1` when accelerating, and writing `w0` for the current speed and
`alpha` for the acceleration currently in force,

```
c0 = remaining(0) - sigma * (w0^2 - v_target^2) / (2 * a_ramp)
c1 = -w0 * (1 + sigma * alpha / a_ramp)
c2 = -(alpha / 2) * (1 + sigma * alpha / a_ramp)
```

and the arming time is the smallest non negative root of `c0 + c1 t + c2 t^2 = 0`. A non positive `c0`
means the point has already gone by and the ramp must start at once.

An event is **not** armed, and falls back to the plain behaviour at its trigger, when its target
position falls inside a rolling zone: either a pass is engaged and will still be engaged there, or a
stand still to be engaged lies between the leading extremity and the target position. A ramp cannot be
planned across a pass, because the bite reassigns the speed anyway. When only the anticipation reaches
back into the rolling zone while the target position is already in free running, the ramp does start
during the pass and the fact is reported.

Zoom rolling is deliberately excluded from this rule: its trigger is the point where the acceleration
starts, following the convention of the offline model.

### Final slowdown towards the coiler

Once the last pass has bitten (`next_pass` past the end of the schedule) and the piece is travelling
forward, the slowdown is planned on the **tail** so that it meets `coiler_v_final` at the coiler,
using the acceleration `a_c` declared on the coiler row. It starts as late as possible, including
while stands are still engaged.

The remaining stands the tail has not yet cleared are walked **backward** from the mandrel. At each
stand the tail will speed up by that pass's lambda, so the speed required just before tail-out is
the speed required just after it, divided by lambda. Between stands the tail is held at deceleration
`a_c`. The walk yields a waypoint `(x_wp, v_wp)`: the first remaining stand at the tail speed it
must have there, or the coiler itself at `v_final` when nothing is left engaged. Targeted braking
is then applied to the tail toward that waypoint, exactly as for a reversal.

When braking starts the command is put on the leading extremity:

```
ramp_accel      = a_c * lam
nominal_target  = coiler_v_final * lam
zoom_factor     = 1
```

so the tail decelerates at `a_c` toward `coiler_v_final`. At every later tail-out `lam` falls and
the same assignment is repeated: the commanded rate steps down, the tail deceleration stays
constant. Section events and zoom are ignored once this slowdown has started.

If the tail has already passed the latest start, braking begins at once. The speed it would then
have at the mandrel, including the jumps at the remaining tail-outs, is reported when it exceeds
`coiler_v_final`.

**Reversal wait**: two zero velocity segments are emitted for the duration of the `reversing_delay`,
then `direction` is flipped, the approach speed of the next pass is assigned together with the
acceleration of its stand.

## 5. Post-processing

* **virtual head**: the head trajectory exactly as integrated, unconstrained by the coiler. This is the
  one driving the zoom rolling trigger.
* **physical head**: the virtual head capped at the coiler position. The capping introduces a new knot
  at the crossing instant, computed in closed form.
* **conservation check**: the integrated final length must match
  `L_slab * (h_slab * w_slab) / (h_final * w_final)`. With this model they match by construction: a
  deviation signals an input or implementation error.

## 6. Mass flow balance in the tandem

In the finishing mill the strip between two stands has a fixed length, so the mass flow balance is not
a check but a constraint: inconsistent input speeds would describe an impossible motion. For every
group of stands carrying the same group label and containing a pass marked as master:

```
flux      = v_exit(master) * h_out(master) * w_out(master)
v_exit(i) = flux / (h_out(i) * w_out(i))
```

Deviations from the entered values are reported, not silenced.

## 7. Gap between pieces

The rear extremity of a piece is `min(head, tail)` and the front one `max(head, tail)`. Since the
material head always remains the extremity furthest downstream, including during reverse passes, those
two expressions reduce respectively to the tail of the piece in front and the head of the one behind.
The invariant `x_head >= x_tail` must be verified, not assumed.

```
gap(t) = tail_front(t) - head_rear(t)
```

The difference between two segmented trajectories is a **piecewise quadratic** function: the knots of
the two trajectories are merged and on each interval

```
f(t) = c0 + c1*(t - t0) + c2*(t - t0)^2
c0 = xA(t0) - xB(t0)      c1 = vA(t0) - vB(t0)      c2 = (aA - aB) / 2
```

The minimum is searched at the ends of each piece and at the vertex, when it falls inside. The first
instant at which the gap drops below a threshold is obtained by solving `f(t) = threshold` on each
piece. Both are exact: there is no sampling.

The time gap at the critical point is the interval between the tail of the piece in front passing a
position and the head of the one behind reaching it, obtained by looking for the last crossing of the
critical position by the tail of the front piece before the critical instant.

Every pair of pieces that coexists on the line must be compared, not only the adjacent ones: with a
reversing roughing mill the constraint often falls between piece N and N+2.

## 8. Pacing studies

In open-loop mode the pieces are decoupled: every product is simulated once and the copies are obtained
by shifting the trajectories in time by `i * pacing`.

* **gap versus pacing curve**: for every value of the scan the sequence is built and the minimum over
  all pairs is taken.
* **minimum feasible pacing**: with reverse passes the minimum gap is **not monotonic** in the pacing,
  so a blind bisection does not apply. The curve is scanned, the last infeasible point is taken and the
  interval immediately after it is refined by bisection.
* **robustness**: pass speeds are perturbed within a tolerance, dead times and release instants with a
  Gaussian dispersion, the tandem mass flow balance is re-applied, every piece is re-simulated
  independently and the fraction of runs violating the threshold is counted. The perturbation must be
  applied **before** the mass flow balance, so that in the tandem only the perturbation of the master
  stand matters and the schedule stays physical.

## 9. Costs

A complete simulation of a mill with thirteen passes costs about 0.4 ms and produces roughly fifty
segments per extremity. A scan of a hundred pacing values costs a few tens of milliseconds, a Monte
Carlo of ten thousand runs a few seconds. The bottleneck is not the computation but the drawing:
sampling the trajectories at a fixed step would produce millions of points and make the interface
unusable, whereas segments are drawn using their knots alone, subdividing only the accelerated
stretches.
