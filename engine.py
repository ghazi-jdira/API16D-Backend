"""
API 16D accumulator-sizing calculation engine (server-side).

Direct port of js/engine.js. Holds the confidential data (NIST grid, Cameron
master lookup, BOP specs) and the formulas. Takes a plain inputs dict and
returns a results dict for the frontend. The Cameron shear constants and the
raw lookup tables are NEVER included in the returned payload.
"""
import json
import math
import os

from nist import load_nist

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load(name):
    with open(os.path.join(_DATA_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


MASTER_LOOKUP = _load("masterLookup.json")   # "BOP|RAM|Grade" -> [C1,C2,C3,sigma,desc]
BOP_SPECS = _load("bopSpecs.json")            # [{name,rwp,open,close,ratio,pclose,note}]
LISTS = _load("lists.json")
NIST = load_nist()

_SPEC_BY_NAME = {s["name"]: s for s in BOP_SPECS}


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ---- Shear Pressure Calculator (Cameron EB702D) -------------------------
def _shear_pressure(sh):
    key = "{}|{}|{}".format(sh.get("bopType"), sh.get("ramType"), sh.get("pipeGrade"))
    row = MASTER_LOOKUP.get(key)
    out = {"found": bool(row)}
    if not row:
        return out, 0.0
    C1, C2, C3, sigma, desc = row
    od = sh["od"]
    wall = sh["wall"]
    ppf = sh["ppf"]
    pw = sh["pw"]
    _id = od - 2 * wall
    max_op_override = sh.get("maxOpOverride")
    if _is_num(max_op_override):
        max_op = max_op_override
    else:
        max_op = LISTS["maxOpPressure"].get(sh.get("bopType"), float("nan"))
    method1 = ((C3 * ppf * sigma) + (pw * C2)) / C1
    method2 = ((C3 * sigma) * ((od * od - _id * _id) * 2.92) + (pw * C2)) / C1
    # Note: C1/C2/C3/sigma (the confidential constants) are intentionally NOT
    # placed in `out` -- only derived results are returned to the client.
    out.update({
        "ramDesc": desc,
        "id": _id,
        "maxOp": max_op,
        "method1": method1,
        "method2": method2,
        "pct1": method1 / max_op if max_op else float("nan"),
        "pct2": method2 / max_op if max_op else float("nan"),
        "capable1": method1 < max_op if max_op else False,
        "capable2": method2 < max_op if max_op else False,
    })
    return out, method1


# ---- Equipment-row resolution -------------------------------------------
def _resolve_method_b(rows):
    resolved = []
    for r in rows:
        name = r.get("equip")
        s = _SPEC_BY_NAME.get(name)
        if not name or not s:
            continue
        ratio = s["ratio"] if _is_num(s.get("ratio")) else None
        if _is_num(s.get("pclose")):
            pclose = s["pclose"]
        elif ratio:
            pclose = s["rwp"] / ratio
        else:
            pclose = 0
        resolved.append({
            "name": name, "rwp": s["rwp"], "open": s.get("open"),
            "close": s.get("close"), "ratio": s.get("ratio"), "pclose": pclose,
        })
    fvr = sum(r["close"] for r in resolved if _is_num(r.get("close")))
    return resolved, fvr


def _resolve_method_c(rows):
    resolved = []
    for r in rows:
        name = r.get("equip")
        s = _SPEC_BY_NAME.get(name)
        if not name or not s:
            continue
        ratio = r.get("ratio") if _is_num(r.get("ratio")) else (
            s["ratio"] if _is_num(s.get("ratio")) else None)
        use_phase = _is_num(ratio) and _is_num(r.get("mopflps"))
        if use_phase:
            adjusted = r["mopflps"] + s["rwp"] / ratio
        elif _is_num(s.get("pclose")):
            adjusted = s["pclose"]
        elif _is_num(ratio):
            adjusted = s["rwp"] / ratio
        else:
            adjusted = r["mopflps"] if _is_num(r.get("mopflps")) else 0
        close = r["close"] if _is_num(r.get("close")) else (
            s["close"] if _is_num(s.get("close")) else 0)
        resolved.append({
            "name": name, "rwp": s["rwp"], "close": close,
            "ratio": ratio, "mopflps": r.get("mopflps"), "adjusted": adjusted,
        })
    fvr = sum(r["close"] for r in resolved if _is_num(r.get("close")))
    return resolved, fvr


# ---- Full model ----------------------------------------------------------
def compute(inp):
    NI = NIST
    Patm = inp["atmospheric"]
    Th = inp["surfaceTemp"] + inp["tempRange"]
    Tn = inp["surfaceTemp"]
    Tl = inp["surfaceTemp"] - inp["tempRange"]

    pump_stop = inp["rwp"]
    pump_start = inp["rwp"] * 0.9

    shear, shear_pr = _shear_pressure(inp["shear"])

    mb_rows, fvrB = _resolve_method_b(inp["methodBRows"])
    mc_rows, fvrC = _resolve_method_c(inp["methodCRows"])

    mop_override = inp.get("mopOverride")
    base = mop_override if _is_num(mop_override) else shear_pr
    max_pclose_b = max([x["pclose"] for x in mb_rows if _is_num(x.get("pclose"))], default=0)
    max_adj_c = max([x["adjusted"] for x in mc_rows if _is_num(x.get("adjusted"))], default=0)
    prB = max(max_pclose_b, base)
    prC = max(max_adj_c, base)

    # ---- Method B ----
    chargedB = pump_stop + Patm
    rho1BH = NI.density(Th, chargedB)
    rho1BN = NI.density(Tn, chargedB)
    rho1BL = NI.density(Tl, chargedB)
    mopB_psia = prB + Patm
    rho2BH = NI.density(Th, mopB_psia)
    rho2BN = NI.density(Tn, mopB_psia)
    rho2BL = NI.density(Tl, mopB_psia)
    rho0B = 1 / (1.4 / rho2BL - 1.4 / rho1BL + 1 / rho1BH)
    precharge_b_psia = NI.pressure_from_density(Tn, rho0B)
    method_b = {
        "rows": mb_rows, "fvr": fvrB, "pressureRequired": prB,
        "chargedPsig": pump_stop, "chargedPsia": chargedB,
        "rho1BH": rho1BH, "rho1BN": rho1BN, "rho1BL": rho1BL,
        "mopPsig": prB, "mopPsia": mopB_psia,
        "rho2BH": rho2BH, "rho2BN": rho2BN, "rho2BL": rho2BL, "rho0": rho0B,
        "prechargePsia": precharge_b_psia, "prechargePsig": precharge_b_psia - Patm,
    }

    # ---- Method C ----
    chargedC = pump_start + Patm
    rho1CH = NI.density(Th, chargedC)
    rho1CN = NI.density(Tn, chargedC)
    rho1CL = NI.density(Tl, chargedC)
    S1CH = NI.entropy(Th, chargedC)
    S1CN = NI.entropy(Tn, chargedC)
    S1CL = NI.entropy(Tl, chargedC)
    mopC_psia = prC + Patm
    T2CH = NI.temp_at_entropy(S1CH, mopC_psia)
    T2CN = NI.temp_at_entropy(S1CN, mopC_psia)
    T2CL = NI.temp_at_entropy(S1CL, mopC_psia)
    rho2CH = NI.density(T2CH, mopC_psia)
    rho2CN = NI.density(T2CN, mopC_psia)
    rho2CL = NI.density(T2CL, mopC_psia)
    rho0C = 1 / (1 / rho2CL - 1 / rho1CL + 1 / rho1CH)
    precharge_c_psia = NI.pressure_from_density(Tn, rho0C)
    method_c = {
        "rows": mc_rows, "fvr": fvrC, "pressureRequired": prC,
        "chargedPsig": pump_start, "chargedPsia": chargedC,
        "rho1CH": rho1CH, "rho1CN": rho1CN, "rho1CL": rho1CL,
        "S1CH": S1CH, "S1CN": S1CN, "S1CL": S1CL,
        "mopPsig": prC, "mopPsia": mopC_psia,
        "T2CH": T2CH, "T2CN": T2CN, "T2CL": T2CL,
        "rho2CH": rho2CH, "rho2CN": rho2CN, "rho2CL": rho2CL, "rho0": rho0C,
        "prechargePsia": precharge_c_psia, "prechargePsig": precharge_c_psia - Patm,
    }

    # ---- Combined optimization ----
    rho_XBC = 1.1 * fvrC / (1.4 * fvrB * (1 / rho2CL - 1 / rho1CL) + 1.1 * fvrC * (1 / rho1BH))
    rho_XCB = fvrB / (1.1 * fvrC * (1 / rho2BL - 1 / rho1BL) + fvrB * (1 / rho1CH))
    V0B = fvrB / ((rho1BL - rho2BL) / (1.4 * rho1BL - 0.4 * rho2BL))
    V0C = 1.1 * fvrC / (1 - rho2CL / rho1CL)

    if rho0B < rho_XBC < rho0C:
        rho_overall, branch = rho_XBC, "rho_XBC (intersect)"
    elif rho0C < rho_XCB < rho0B:
        rho_overall, branch = rho_XCB, "rho_XCB (intersect)"
    elif V0B < V0C:
        rho_overall, branch = rho0C, "rho_0C (C governs)"
    else:
        rho_overall, branch = rho0B, "rho_0B (B governs)"
    overall_psia = NI.pressure_from_density(Tn, rho_overall)
    overall_psig = overall_psia - Patm

    pc_override = inp.get("prechargeOverride")
    has_override = _is_num(pc_override)
    # Quirk preserved from workbook: override density looked up at raw psig as psia.
    rho_override = NI.density(Tn, pc_override) if has_override else None
    rho0 = rho_override if has_override else rho_overall
    selected_precharge_psig = pc_override if has_override else overall_psig

    VE_PL_B = (rho0 / rho2BL - rho0 / rho1BL) / 1.0
    VE_VH_B = (1 - rho0 / rho1BH) / 1.4
    VE_B = min(VE_PL_B, VE_VH_B)
    ACR_B = fvrB / VE_B
    VE_PL_C = (rho0 / rho2CL - rho0 / rho1CL) / 1.1
    VE_VH_C = (1 - rho0 / rho1CH) / 1.1
    VE_C = min(VE_PL_C, VE_VH_C)
    ACR_C = fvrC / VE_C
    min_volume = max(ACR_B, ACR_C)

    precharge_min_temp_psia = NI.pressure_from_density(Tl, rho0)
    precharge_max_psig = NI.pressure_from_density(Th, rho0) - Patm
    warn25 = precharge_min_temp_psia > 0.25 * chargedB

    summary = {
        "rho_XBC": rho_XBC, "rho_XCB": rho_XCB, "V0B": V0B, "V0C": V0C,
        "branch": branch, "rhoOverall": rho_overall,
        "overallPsia": overall_psia, "overallPsig": overall_psig,
        "hasOverride": has_override, "rhoOverride": rho_override, "rho0": rho0,
        "selectedPrechargePsig": selected_precharge_psig,
        "VE_PL_B": VE_PL_B, "VE_VH_B": VE_VH_B, "VE_B": VE_B, "ACR_B": ACR_B,
        "VE_PL_C": VE_PL_C, "VE_VH_C": VE_VH_C, "VE_C": VE_C, "ACR_C": ACR_C,
        "minVolume": min_volume,
        "bottles11": math.ceil(min_volume / 9.99 * 100) / 100,
        "bottles15": math.ceil(min_volume / 14 * 100) / 100,
        "bottles11whole": math.ceil(min_volume / 9.99),
        "bottles15whole": math.ceil(min_volume / 14),
        "prechargeOkMinTemp": warn25,
        "prechargeMinTempPsia": precharge_min_temp_psia,
        "prechargeMaxPsig": precharge_max_psig,
        "prechargeOkMaxTemp": precharge_max_psig < inp["rwp"],
    }

    # ---- Volume vs precharge-pressure curve ----
    P1, P2 = chargedB, chargedC
    r1, r2 = rho1BN, rho1CN
    bCoef = (r2 * P1 - r1 * P2) / (P1 * P2 * (P2 - P1))
    aCoef = (r1 - bCoef * P1 * P1) / P1
    points = []
    p0 = 100
    while p0 <= 2500:
        p0a = p0 + Patm
        rc = aCoef * p0a + bCoef * p0a * p0a
        veB = min((rc / rho2BL - rc / rho1BL) / 1, (1 - rc / rho1BH) / 1.4)
        veC = min((rc / rho2CL - rc / rho1CL) / 1.1, (1 - rc / rho1CH) / 1.1)
        vB = fvrB / veB if veB > 0.001 else 2500
        vC = fvrC / veC if veC > 0.001 else 2500
        points.append({"p0": p0, "vB": min(vB, 2600), "vC": min(vC, 2600)})
        p0 += 100
    curve = {"points": points, "optimumPsig": overall_psig,
             "optimumVol": min_volume, "aCoef": aCoef, "bCoef": bCoef}

    return {
        "temps": {"Th": Th, "Tn": Tn, "Tl": Tl},
        "pumpStop": pump_stop, "pumpStart": pump_start,
        "shear": shear, "methodB": method_b, "methodC": method_c,
        "summary": summary, "curve": curve,
    }


def meta():
    """Non-secret data the UI needs to build dropdowns/tables (gated by auth).
    The Cameron master-lookup constants and the NIST grid are never included."""
    return {
        "bopSpecs": BOP_SPECS,
        "lists": {
            "bopTypes": LISTS["bopTypes"],
            "ramTypes": LISTS["ramTypes"],
            "pipeGrades": LISTS["pipeGrades"],
        },
    }
