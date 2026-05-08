"""
确定性排盘 tool。

关键点：
- 由 lunar_python 计算四柱、起运、大运、流年；模型不参与排盘，只解读。
- 口径写死并对外说明：月柱以节气为界、性别 1=男 0=女、大运按 lunar_python 默认（流派 1）。
- 失败/版本差异时给出明确报错，而不是悄悄退化。

依赖：pip install lunar_python
"""

from typing import List, Dict, Any, Iterable

try:
    from lunar_python import Solar
except ImportError as e:
    raise ImportError(
        "需要 lunar_python：pip install lunar_python"
    ) from e


_GENDER_MAP = {
    "男": 1, "女": 0,
    "male": 1, "female": 0,
    "M": 1, "F": 0,
    1: 1, 0: 0,
}


def _gender_to_int(g) -> int:
    if g in _GENDER_MAP:
        return _GENDER_MAP[g]
    raise ValueError(f"无法识别的性别: {g!r}（需为 男/女、male/female、1/0）")


def _safe(call, default=None):
    try:
        return call()
    except Exception:
        return default


def compute_chart(
    birth_year: int,
    birth_month: int,
    birth_day: int,
    birth_hour: int = 12,
    birth_minute: int = 0,
    gender="男",
    n_dayun: int = 10,
) -> Dict[str, Any]:
    """
    根据公历出生时刻 + 性别返回排盘结果。

    返回结构（节选）：
      {
        "input": {...},
        "natal": {"year","month","day","hour","day_master","month_branch", ...},
        "qi_yun": {"start_solar_date": "...", "duration_years": N, ...},
        "da_yun": [
          {"index": i, "ganzhi": "...", "start_age": ..., "end_age": ...,
           "start_year": ..., "end_year": ...},
          ...
        ]
      }
    """
    g = _gender_to_int(gender)

    solar = Solar.fromYmdHms(
        birth_year, birth_month, birth_day, birth_hour, birth_minute, 0
    )
    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    natal = {
        "year": ec.getYear(),
        "month": ec.getMonth(),
        "day": ec.getDay(),
        "hour": ec.getTime(),
        "day_master": ec.getDayGan(),
        "month_branch": _safe(ec.getMonthZhi),
        "year_animal": _safe(lunar.getYearShengXiao),
        "lunar_date": _safe(
            lambda: f"{lunar.getYearInGanZhi()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"
        ),
    }

    yun = ec.getYun(g)

    qi_yun: Dict[str, Any] = {
        "duration_years": _safe(yun.getStartYear),
        "duration_months": _safe(yun.getStartMonth),
        "duration_days": _safe(yun.getStartDay),
    }
    start_solar = _safe(yun.getStartSolar)
    if start_solar is not None:
        qi_yun["start_solar_date"] = (
            f"{start_solar.getYear()}-{start_solar.getMonth():02d}-{start_solar.getDay():02d}"
        )

    da_yun_list: List[Dict[str, Any]] = []
    raw = yun.getDaYun(n_dayun)
    for i, dy in enumerate(raw):
        # lunar_python 的 index 0 通常是「童限」（起运前），保留但用 index 区分
        da_yun_list.append({
            "index": i,
            "is_pre_qi_yun": i == 0,
            "ganzhi": _safe(dy.getGanZhi),
            "start_age": _safe(dy.getStartAge),
            "end_age": _safe(dy.getEndAge),
            "start_year": _safe(dy.getStartYear),
            "end_year": _safe(dy.getEndYear),
        })

    return {
        "input": {
            "birth": f"{birth_year}-{birth_month:02d}-{birth_day:02d} {birth_hour:02d}:{birth_minute:02d}",
            "gender": "男" if g == 1 else "女",
            "calendar_note": "公历，月柱以节气为界，未做真太阳时校正",
        },
        "natal": natal,
        "qi_yun": qi_yun,
        "da_yun": da_yun_list,
    }


def chart_natal_only(chart: Dict[str, Any]) -> Dict[str, Any]:
    """给 Round 1 的最小信息：只看四柱，不暴露大运。"""
    return {"input": chart["input"], "natal": chart["natal"]}


def _ganzhi_for_year(y: int) -> str:
    # 用当年 6 月 1 日避开立春边界
    return Solar.fromYmd(y, 6, 1).getLunar().getYearInGanZhi()


def _annotate_dayun(year: int, da_yun: List[Dict[str, Any]]) -> Dict[str, Any]:
    for dy in da_yun:
        sy, ey = dy.get("start_year"), dy.get("end_year")
        if sy is not None and ey is not None and sy <= year <= ey:
            return {"in_dayun_index": dy["index"], "in_dayun_ganzhi": dy["ganzhi"]}
    return {"in_dayun_index": None, "in_dayun_ganzhi": None}


def liunian_for_year_range(
    start_year: int, end_year: int, chart: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if end_year < start_year:
        start_year, end_year = end_year, start_year
    out = []
    for y in range(start_year, end_year + 1):
        item = {"year": y, "ganzhi": _ganzhi_for_year(y)}
        item.update(_annotate_dayun(y, chart["da_yun"]))
        out.append(item)
    return out


def liunian_for_years(
    years: Iterable[int], chart: Dict[str, Any]
) -> List[Dict[str, Any]]:
    out = []
    for y in sorted({int(y) for y in years if y is not None}):
        item = {"year": y, "ganzhi": _ganzhi_for_year(y)}
        item.update(_annotate_dayun(y, chart["da_yun"]))
        out.append(item)
    return out
