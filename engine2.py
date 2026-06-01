"""
API 16D — 2nd edition (Dixstone) accumulator sizing engine.

Surface BOP stack, two design methods evaluated side by side:

  * Method A  — ideal-gas (pressure-ratio) volumetric efficiency. No NIST.
  * Method B  — real-gas volumetric efficiency using NIST nitrogen DENSITY
                (forward T,P->rho and inverse T,rho->P lookups). No entropy.

This is a direct port of the workbook
"API_16D_dixstone_2nd_edition_Wellbore Pressure, Pw 3000(psi).xlsx"
(sheets: Inputs, Method A, Method B, NIST Lookups). It reuses the existing
NIST density grid (data/nist.json) via nist.Nist — the same grid the 1st
edition uses.

Design factors per Table 2:
            Volume Limited   Pressure Limited
  Method A       1.5               1.0
  Method B       1.4               1.0
"""
import math

# Design factors (Table 2)
METHOD_A_VOL = 1.5
METHOD_A_PRES = 1.0
METHOD_B_VOL = 1.4
METHOD_B_PRES = 1.0


def _fvr(equipment):
    """Functional Volume Requirement = max(sum of closing vols, sum of opening vols)."""
    close_sum = sum((e.get("close") or 0.0) for e in equipment)
    open_sum = sum((e.get("open") or 0.0) for e in equipment)
    return max(close_sum, open_sum), close_sum, open_sum


def _mop(equipment, operator_shear_psig):
    """MOP pressure requirement = max(pressure-to-close across stack, operator shear)."""
    pcloses = [(e.get("pclose") or 0.0) for e in equipment]
    return max(pcloses + [operator_shear_psig])


def _round_up(x):
    return int(math.ceil(x - 1e-9))


def compute(inp, nist):
    atm = float(inp.get("atm", 14.7))
    Ts = float(inp.get("surfaceTempF", 85.0))          # surface temp at precharge
    Tmax = float(inp.get("maxSurfaceTempF", 100.0))    # max surface temp (ideal rise)
    P1 = float(inp["chargedPsig"])                     # Condition 1 charged / pump stop
    P0 = float(inp["prechargePsig"])                   # Condition 0 specified precharge
    bottleVol = float(inp.get("gasVolPerBottle", 11.0))
    bottleRating = float(inp.get("bottleRatingPsig", 3000.0))
    operatorShear = float(inp.get("operatorShearPsig", 0.0))
    equipment = inp.get("equipment", [])

    FVR, closeSum, openSum = _fvr(equipment)
    if "fvrOverride" in inp and inp["fvrOverride"] not in (None, ""):
        FVR = float(inp["fvrOverride"])

    P2 = _mop(equipment, operatorShear)                # Condition 2 MOP (psig)

    # psia
    P0a, P1a, P2a = P0 + atm, P1 + atm, P2 + atm

    # ---------------- Method A (ideal gas) ----------------
    VEp_a = (P0a / P2a - P0a / P1a) / METHOD_A_PRES
    VEv_a = (1.0 - P0a / P1a) / METHOD_A_VOL
    VE_a = min(VEp_a, VEv_a)

    bottlesRaw_a = FVR / VE_a / bottleVol
    bottles_a = _round_up(bottlesRaw_a)
    gasTotal_a = bottles_a * bottleVol          # total gas vol at precharge (gal)
    usable_a = gasTotal_a * VE_a

    # Optimum precharge (ideal): 1/(1.5/P2a - 0.5/P1a) (psia) -> psig
    optPre_a_psia = 1.0 / (METHOD_A_VOL / P2a - (METHOD_A_VOL - 1.0) / P1a)
    optPre_a_psig = optPre_a_psia - atm
    # Pressure rise to max temp (ideal gas): P_T2 = P0a * (Tmax+459.67)/(Ts+459.67)
    presAtMaxT_a_psia = P0a * (Tmax + 459.67) / (Ts + 459.67)
    presAtMaxT_a_psig = presAtMaxT_a_psia - atm

    perf_a = _perf_pressure(gasTotal_a, P0, P1, P2, P0a, P1a, P2a, atm)
    summary_a = _summary(perf_a, FVR, METHOD_A_PRES, METHOD_A_VOL)

    methodA = {
        "VEp": VEp_a, "VEv": VEv_a, "VE": VE_a,
        "bottlesRaw": bottlesRaw_a, "bottles": bottles_a,
        "gasTotal": gasTotal_a, "usable": usable_a,
        "optPrechargePsig": optPre_a_psig, "optPrechargePsia": optPre_a_psia,
        "presAtMaxTempPsig": presAtMaxT_a_psig,
        "performance": perf_a, "summary": summary_a,
    }

    # ---------------- Method B (NIST density) ----------------
    rho1 = nist.density(Ts, P1a)                # charged density
    rho2 = nist.density(Ts, P2a)               # MOP density
    rho0_opt = 1.0 / (METHOD_B_VOL / rho2 - (METHOD_B_VOL - 1.0) / rho1)
    optPre_b_psia = nist.pressure_from_density(Ts, rho0_opt)
    optPre_b_psig = optPre_b_psia - atm

    rho0 = nist.density(Ts, P0a)                # specified precharge density
    presAtMaxT_b_psia = nist.pressure_from_density(Tmax, rho0)
    presAtMaxT_b_psig = presAtMaxT_b_psia - atm

    VEp_b = (rho0 / rho2 - rho0 / rho1) / METHOD_B_PRES
    VEv_b = (1.0 - rho0 / rho1) / METHOD_B_VOL
    VE_b = min(VEp_b, VEv_b)

    bottlesRaw_b = FVR / VE_b / bottleVol
    bottles_b = _round_up(bottlesRaw_b)
    gasTotal_b = bottles_b * bottleVol
    usable_b = gasTotal_b * VE_b

    perf_b = _perf_density(gasTotal_b, P0, P1, P2, P0a, P1a, P2a, rho0, rho1, rho2)
    summary_b = _summary(perf_b, FVR, METHOD_B_PRES, METHOD_B_VOL)

    methodB = {
        "rho1": rho1, "rho2": rho2, "rho0": rho0, "rho0Opt": rho0_opt,
        "VEp": VEp_b, "VEv": VEv_b, "VE": VE_b,
        "bottlesRaw": bottlesRaw_b, "bottles": bottles_b,
        "gasTotal": gasTotal_b, "usable": usable_b,
        "optPrechargePsig": optPre_b_psig, "optPrechargePsia": optPre_b_psia,
        "presAtMaxTempPsig": presAtMaxT_b_psig,
        "performance": perf_b, "summary": summary_b,
    }

    return {
        "inputs": {
            "FVR": FVR, "closeSum": closeSum, "openSum": openSum,
            "surfaceTempF": Ts, "maxSurfaceTempF": Tmax,
            "chargedPsig": P1, "prechargePsig": P0, "mopPsig": P2,
            "operatorShearPsig": operatorShear,
            "gasVolPerBottle": bottleVol, "bottleRatingPsig": bottleRating,
            "atm": atm,
        },
        "methodA": methodA,
        "methodB": methodB,
    }


def _perf_pressure(gasTotal, P0, P1, P2, P0a, P1a, P2a, atm):
    """Method A performance table — gas volume by pressure ratio P0a/Px."""
    rows = []
    # Condition 0: precharge
    rows.append(_row("Condition 0: Precharge", P0, P0a, gasTotal, 0.0))
    # Condition 1: charged
    g1 = gasTotal * P0a / P1a
    rows.append(_row("Condition 1: Charged", P1, P1a, g1, gasTotal - g1))
    # Condition 2: MOP
    g2 = min(gasTotal, gasTotal * P0a / P2a)
    rows.append(_row("Condition 2: MOP", P2, P2a, g2, gasTotal - g2))
    # Condition 3: fully discharged (P = atm)
    g3 = min(gasTotal, gasTotal * P0a / atm)
    rows.append(_row("Condition 3: Fully discharged", 0.0, atm, g3, gasTotal - g3))
    return rows


def _perf_density(gasTotal, P0, P1, P2, P0a, P1a, P2a, rho0, rho1, rho2):
    """Method B performance table — gas volume by density ratio rho0/rhox."""
    rows = []
    rows.append(_row("Condition 0: Precharge", P0, P0a, gasTotal, 0.0, rho0))
    g1 = gasTotal * rho0 / rho1
    rows.append(_row("Condition 1: Charged", P1, P1a, g1, gasTotal - g1, rho1))
    g2 = min(gasTotal, gasTotal * rho0 / rho2)
    rows.append(_row("Condition 2: MOP", P2, P2a, g2, gasTotal - g2, rho2))
    # Condition 3 == Condition 0 (precharge) in Method B
    rows.append(_row("Condition 3: Fully discharged", P0, P0a, gasTotal, 0.0, rho0))
    return rows


def _row(label, psig, psia, gas, liquid, rho=None):
    r = {"label": label, "psig": psig, "psia": psia, "gas": gas, "liquid": liquid}
    if rho is not None:
        r["rho"] = rho
    return r


def _summary(perf, FVR, presFactor, volFactor):
    """Pressure design (Cond1->Cond2) and Volume design (Cond1->Cond3)."""
    liq1 = perf[1]["liquid"]   # Condition 1 charged liquid
    liq2 = perf[2]["liquid"]   # Condition 2 MOP liquid
    liq3 = perf[3]["liquid"]   # Condition 3 liquid
    pres_actual = liq1 - liq2
    pres_factored = pres_actual / presFactor
    vol_actual = liq1 - liq3
    vol_factored = vol_actual / volFactor
    return {
        "pressureDesign": {
            "actual": pres_actual, "factored": pres_factored,
            "fvr": FVR, "meets": pres_factored >= FVR,
        },
        "volumeDesign": {
            "actual": vol_actual, "factored": vol_factored,
            "fvr": FVR, "meets": vol_factored >= FVR,
        },
    }
