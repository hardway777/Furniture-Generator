"""solver - Height solver - turns a shelf/drawer spec into real z bands.

Moved verbatim from the single-module addon; no body was edited during the move.
"""
from .core import warn

# [ANCHOR: SOLVER_HEIGHTS]
# ============================================================
def solver_warning(message):
    """Collect a non-fatal height configuration conflict for the current generation run."""
    warn(message)


def solve_element_heights(items, total_space, min_val=0.05, label=""):
    """Parametric solver guaranteeing elements sum strictly to total_space without gaps.

    METERS heights are exact and are never rescaled - PERCENT/AUTO items share the space
    that is left. A warning is collected when the requested configuration does not fit:
    spare space is absorbed by the last element, an overflow is scaled down proportionally.
    """
    n = len(items)
    if n == 0:
        return []
    if n == 1:
        return [max(min_val, total_space)]

    modes = [getattr(item, "height_mode", 'METERS') for item in items]
    results = [0.0] * n

    fixed_sum = 0.0
    pct_items = []
    auto_indices = []

    for idx, item in enumerate(items):
        if modes[idx] == 'METERS':
            h = max(min_val, getattr(item, "height", 0.22))
            results[idx] = h
            fixed_sum += h
        elif modes[idx] == 'PERCENT':
            pct_items.append((idx, max(0.1, getattr(item, "height_pct", 33.3))))
        else:
            auto_indices.append(idx)

    flexible = len(pct_items) + len(auto_indices)
    rem_after_fixed = total_space - fixed_sum

    if flexible and rem_after_fixed <= 0.0:
        for idx, _ in pct_items:
            results[idx] = min_val
        for idx in auto_indices:
            results[idx] = min_val
        solver_warning(
            f"{label}: exact heights already use {fixed_sum:.3f} m of {total_space:.3f} m, "
            f"flexible zones clamped to {min_val:.3f} m"
        )
    elif flexible:
        total_pct = sum(p for _, p in pct_items)
        pct_space_used = 0.0
        for idx, pct in pct_items:
            if auto_indices:
                h = (pct / 100.0) * rem_after_fixed
            else:
                share = (pct / total_pct) if total_pct > 0 else (1.0 / len(pct_items))
                h = share * rem_after_fixed
            results[idx] = max(min_val, h)
            pct_space_used += results[idx]

        if auto_indices:
            rem_for_auto = max(0.0, rem_after_fixed - pct_space_used)
            auto_h = max(min_val, rem_for_auto / len(auto_indices))
            for idx in auto_indices:
                results[idx] = auto_h

    diff = total_space - sum(results)
    if abs(diff) > 1e-4 and sum(results) > 1e-4:
        # Exact heights stay untouched: re-spread the difference over flexible elements only.
        if flexible and fixed_sum <= total_space + 1e-6:
            flex_sum = sum(results) - fixed_sum
            if flex_sum > 1e-6:
                scale = max(0.0, rem_after_fixed) / flex_sum
                for idx in range(n):
                    if modes[idx] != 'METERS':
                        results[idx] *= scale
            diff = total_space - sum(results)

        if abs(diff) > 1e-4:
            if diff > 0.0:
                # Nothing flexible left: the last element absorbs the remainder, which matches
                # the geometry, because the topmost zone always reaches the carcass top.
                results[-1] += diff
                solver_warning(
                    f"{label}: {diff:.3f} m unused by fixed heights of {total_space:.3f} m, "
                    f"added to the last element"
                )
            else:
                curr_sum = sum(results)
                scale = total_space / curr_sum
                results = [r * scale for r in results]
                solver_warning(
                    f"{label}: fixed heights {curr_sum:.3f} m exceed {total_space:.3f} m, "
                    f"scaled down by {scale:.3f}"
                )

    return results


# ============================================================
