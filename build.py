#!/usr/bin/env python3
"""Build an entirely static, self-contained Mumbai PM2.5 data story.

First build, with network access: python build.py --prepare-cache --fetch-weather
Every subsequent build, offline: python build.py

The browser-facing index.html contains inline CSS and SVG. It makes no requests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import math
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "weather_raw"
TRAIN_CACHE = DATA / "station_pm25_hourly.csv.gz"
STATIONS_CACHE = DATA / "stations.csv"
WEATHER_CACHE = DATA / "weather_hourly.csv.gz"
IST = "Asia/Kolkata"
COLORS = {"Malad West": "#f4a261", "Shivaji Nagar": "#f26868", "Byculla": "#74c0b3", "Borivali East": "#a0a5eb"}
ORDER = ["Malad West", "Shivaji Nagar", "Byculla", "Borivali East"]
FULL = {"Malad West": "Malad West · IITM", "Shivaji Nagar": "Shivaji Nagar · BMC", "Byculla": "Byculla · BMC", "Borivali East": "Borivali East · IITM"}


def short_station(name: str) -> str:
    return next(s for s in ORDER if name.startswith(s))


def num(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def cache_challenge_data() -> None:
    """Make a small, reusable snapshot from the already downloaded challenge files."""
    DATA.mkdir(parents=True, exist_ok=True)
    source = HERE.parent / "input" / "Train (3).csv"
    station_source = HERE.parent / "input" / "Stations (2).csv"
    if not source.exists() or not station_source.exists():
        raise FileNotFoundError("Challenge Train and Stations files are needed for --prepare-cache")
    df = pd.read_csv(source, usecols=["timestamp_ist", "pm25", "location_id", "station_name", "flag_high_1000"])
    df["timestamp_ist"] = pd.to_datetime(df["timestamp_ist"], utc=True).dt.tz_convert(IST)
    df["target_start_ist"] = df["timestamp_ist"] - pd.Timedelta(hours=1)
    df = df.loc[(df["flag_high_1000"] == False) & df["pm25"].between(0, 1000)].copy()  # noqa: E712
    df["station"] = df["station_name"].map(short_station)
    df = df[["target_start_ist", "location_id", "station", "pm25"]].sort_values(["target_start_ist", "station"])
    if df.duplicated(["target_start_ist", "location_id"]).any():
        raise ValueError("Duplicate station hours in challenge data")
    df.to_csv(TRAIN_CACHE, index=False, compression="gzip", float_format="%.5f")
    shutil.copyfile(station_source, STATIONS_CACHE)
    (DATA / "challenge_provenance.json").write_text(json.dumps({
        "source": "Google Mumbai Data Challenge; CPCB CAAQMS measurements via OpenAQ",
        "catalogue": "https://india.climateverse.net/dataverse/google-air-quality-forecasting-challenge",
        "challenge_data": "https://zindi.world/competitions/google-mumbai-data-challenge/data",
        "local_input_files": [source.name, station_source.name],
        "license": "CC BY-SA 4.0 as stated by the Zindi challenge",
        "cleaning": "Retain nonnegative PM2.5 <= 1000 and remove flag_high_1000 rows; shift source end timestamp back one hour",
        "cached_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(df)
    }, indent=2) + "\n")
    print(f"Cached {len(df):,} cleaned challenge station-hours in {TRAIN_CACHE.name}")


def fetch_weather() -> None:
    """Fetch one frozen Open-Meteo historical snapshot; never used by the HTML at runtime."""
    if not STATIONS_CACHE.exists():
        raise FileNotFoundError("Run --prepare-cache before --fetch-weather")
    RAW.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(STATIONS_CACHE)
    rows = []
    provenance = {"catalogue": "https://india.climateverse.net/dataset.xhtml?persistentId=doi:10.71646/XXOBKO",
                  "provider": "Open-Meteo Historical Weather API", "period": "2026-09-01 to 2026-11-06",
                  "cached_utc": datetime.now(timezone.utc).isoformat(),
                  "variables": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precipitation"],
                  "note": "Modelled grid-cell weather. No claim of station-level meteorological measurement.", "requests": []}
    for s in stations.itertuples(index=False):
        name = short_station(s.station_name)
        params = {"latitude": float(s.latitude), "longitude": float(s.longitude),
                  "start_date": "2026-09-01", "end_date": "2026-11-06",
                  "hourly": ",".join(provenance["variables"]), "timezone": IST}
        url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.load(response)
        if "hourly" not in payload or len(payload["hourly"]["time"]) < 1400:
            raise ValueError(f"Weather response incomplete for {name}: {str(payload)[:250]}")
        (RAW / f"{name.lower().replace(' ', '_')}.json").write_text(json.dumps(payload, separators=(",", ":")))
        provenance["requests"].append(url)
        frame = pd.DataFrame(payload["hourly"])
        frame["station"] = name
        rows.append(frame)
        print(f"Fetched {name}: {len(frame):,} weather hours")
    weather = pd.concat(rows, ignore_index=True)
    weather.rename(columns={"time": "hour_start_ist"}, inplace=True)
    weather.to_csv(WEATHER_CACHE, index=False, compression="gzip")
    (DATA / "weather_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for p in [TRAIN_CACHE, STATIONS_CACHE, WEATHER_CACHE]:
        if not p.exists():
            raise FileNotFoundError(f"Missing {p}. First run python build.py --prepare-cache --fetch-weather")
    obs = pd.read_csv(TRAIN_CACHE, parse_dates=["target_start_ist"])
    obs["date"] = obs["target_start_ist"].dt.date
    obs["hour"] = obs["target_start_ist"].dt.hour
    stations = pd.read_csv(STATIONS_CACHE)
    weather = pd.read_csv(WEATHER_CACHE, parse_dates=["hour_start_ist"])
    weather["date"] = weather["hour_start_ist"].dt.date
    return obs, stations, weather


def svg_open(label: str, desc: str, w: int, h: int, css: str = "") -> str:
    return f'<svg class="{css}" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" xmlns="http://www.w3.org/2000/svg"><title>{esc(label)}</title><desc>{esc(desc)}</desc>'


def text(x: float, y: float, value: object, cls: str = "axis", anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{esc(value)}</text>'


def line(x1: float, y1: float, x2: float, y2: float, cls: str = "grid", extra: str = "") -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}" {extra}/>'


def poly(points: list[tuple[float, float]], color: str, width: float = 2.5, opacity: float = 1) -> str:
    if len(points) < 2:
        return ""
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}"/>'


def chart_daily(daily: pd.DataFrame, start: str, end: str, festival: str | None = None) -> str:
    width, height = 1040, 380
    l, r, t, b = 52, 75, 25, 49
    dates = pd.date_range(start, end, freq="D")
    selected = daily.loc[daily["date"].between(dates[0].date(), dates[-1].date())]
    cap = max(75, math.ceil(float(selected["pm25"].quantile(.97)) / 25) * 25)
    cap = min(cap, 250)
    x = lambda d: l + (pd.Timestamp(d) - dates[0]).days / max(1, len(dates) - 1) * (width - l - r)
    y = lambda v: t + (1 - min(v, cap) / cap) * (height - t - b)
    out = [svg_open("Daily PM2.5 at four Mumbai stations", "Daily station medians; lines stop when fewer than twelve hourly readings are available. Values above chart ceiling are capped.", width, height, "chart-svg")]
    for value in [0, cap / 4, cap / 2, cap * .75, cap]:
        yy = y(value)
        out += [line(l, yy, width-r, yy), text(l-9, yy+4, num(value), "axis", "end")]
    for d in dates[::max(1, int(math.ceil(len(dates)/7)))]:
        xx = x(d)
        out += [line(xx, t, xx, height-b, "vgrid"), text(xx, height-18, d.strftime("%d %b"), "axis", "middle")]
    if festival:
        fd = pd.Timestamp(festival)
        if dates[0] <= fd <= dates[-1]:
            xx = x(fd)
            out += [line(xx,t,xx,height-b,"festival-line"), text(xx+7,t+17,"Diwali","event")]
    for station in ORDER:
        station_data = selected.loc[selected.station == station].set_index("date")
        segment: list[tuple[float,float]] = []
        for date in dates.date:
            if date in station_data.index:
                row = station_data.loc[date]
                if isinstance(row,pd.DataFrame): row = row.iloc[0]
                if row["count"] >= 12:
                    segment.append((x(date),y(float(row.pm25))))
                    continue
            out.append(poly(segment,COLORS[station])); segment=[]
        out.append(poly(segment,COLORS[station]))
    out += [text(l,15,"PM₂.₅ · µg/m³","unit"),"</svg>"]
    return "".join(out)


def chart_coverage(daily: pd.DataFrame, start: str, end: str) -> str:
    dates = pd.date_range(start, end, freq="D")
    width, height = 1040, 265
    l,r,t = 150,30,28
    gap=3
    cell=(width-l-r)/len(dates)
    lookup={(r.station,r.date):int(r["count"]) for _,r in daily.iterrows()}
    out=[svg_open("Daily station measurement coverage", "Each square is one day and one station. Lighter squares mean more missing hours; gray means no readings.",width,height,"coverage-svg")]
    for i,s in enumerate(ORDER):
        yy=t+i*43
        out.append(text(l-12,yy+18,s,"rowlabel","end"))
        for j,d in enumerate(dates.date):
            c=lookup.get((s,d),0)
            opacity=.12+.88*c/24 if c else 0
            color=COLORS[s] if c else "#344455"
            out.append(f'<rect x="{l+j*cell:.1f}" y="{yy:.1f}" width="{max(1,cell-gap):.1f}" height="28" rx="2" fill="{color}" opacity="{opacity:.2f}"/>')
    for j in range(0,len(dates),7):
        out.append(text(l+j*cell,height-35,dates[j].strftime("%d %b"),"axis","start"))
    out.append(text(l,height-10,"0 hours","axis"))
    out.append(f'<rect x="{l+64}" y="{height-21}" width="32" height="12" rx="2" fill="#344455"/>')
    out.append(text(l+107,height-10,"24 hours","axis"))
    out.append(f'<rect x="{l+178}" y="{height-21}" width="32" height="12" rx="2" fill="{COLORS["Byculla"]}"/>')
    out.append("</svg>")
    return "".join(out)


def chart_hourly(obs: pd.DataFrame) -> tuple[str,pd.DataFrame]:
    oct_obs=obs.loc[(obs.target_start_ist >= pd.Timestamp("2026-10-01",tz=IST)) & (obs.target_start_ist < pd.Timestamp("2026-11-01",tz=IST))]
    profile=oct_obs.groupby(["station","hour"],as_index=False).pm25.agg(["median","count"]).reset_index(drop=True)
    width,height=1040,355
    l,r,t,b=48,42,28,50
    cap=max(75,math.ceil(profile["median"].max()/25)*25)
    x=lambda h:l+h/23*(width-l-r)
    y=lambda v:t+(1-v/cap)*(height-t-b)
    out=[svg_open("Median October PM2.5 by hour of day", "Four station-specific median hourly curves from October 2026. Each point is a median over observed hours in that month.",width,height,"chart-svg")]
    for v in [0,cap/4,cap/2,cap*.75,cap]:
        yy=y(v);out.extend([line(l,yy,width-r,yy),text(l-8,yy+4,num(v),"axis","end")])
    for h in [0,4,8,12,16,20,23]:
        xx=x(h);out.extend([line(xx,t,xx,height-b,"vgrid"),text(xx,height-18,f"{h:02d}:00","axis","middle")])
    for s in ORDER:
        z=profile[profile.station==s].sort_values("hour")
        out.append(poly([(x(int(v.hour)),y(float(v.median))) for v in z.itertuples()],COLORS[s],3))
    out.extend([text(l,16,"PM₂.₅ · µg/m³","unit"),"</svg>"])
    return "".join(out),profile


def chart_peer_clock(obs: pd.DataFrame) -> tuple[str, dict]:
    """Remove the shared hour by comparing each station with the other three."""
    start = pd.Timestamp("2026-10-01", tz=IST)
    end = pd.Timestamp("2026-11-07", tz=IST)
    window = obs.loc[obs.target_start_ist.between(start, end, inclusive="left")]
    matched = window.pivot(index="target_start_ist", columns="station", values="pm25")[ORDER].dropna()
    if len(matched) < 500:
        raise ValueError("Insufficient four-station matched hours for the peer comparison")
    width, height = 1040, 672
    left, right = 183, 38
    x = lambda hour: left + hour / 23 * (width - left - right)
    out = [svg_open(
        "Station difference from the other three at the same hour",
        "Four small multiples show the median difference in PM2.5 between each station and the median of the other three, by local hour, from 1 October to 6 November 2026. Zero means equal concentrations.",
        width, height, "peer-svg")]
    night = {}
    for i, station in enumerate(ORDER):
        top = 28 + i * 151
        baseline = top + 65
        y = lambda value: baseline - value / 25 * 48
        other = [s for s in ORDER if s != station]
        delta = matched[station] - matched[other].median(axis=1)
        hourly = delta.groupby(delta.index.hour).median().reindex(range(24))
        if hourly.isna().any():
            raise ValueError(f"Missing local hour for {station} peer comparison")
        night_mask = (delta.index.hour >= 20) | (delta.index.hour < 8)
        night[station] = float(delta.loc[night_mask].median())
        for v in [-20, -10, 0, 10, 20]:
            yy = y(v)
            out.append(line(left, yy, width - right, yy, "peer-zero" if v == 0 else "grid"))
            if i == 0:
                out.append(text(left - 9, yy + 4, f"{v:+d}" if v else "0", "axis", "end"))
        out.append(text(8, top + 60, station, "rowlabel"))
        out.append(text(8, top + 83, f"Night {night[station]:+.1f}", "axis"))
        points = [(x(h), y(float(hourly.loc[h]))) for h in range(24)]
        shape = " ".join(f"{xx:.1f},{yy:.1f}" for xx, yy in [(x(0), baseline), *points, (x(23), baseline)])
        out.append(f'<polygon points="{shape}" fill="{COLORS[station]}" opacity=".13"/>')
        out.append(poly(points, COLORS[station], 3.4))
        if i < 3:
            out.append(line(8, top + 139, width - right, top + 139, "vgrid"))
    for hour in [0, 4, 8, 12, 16, 20, 23]:
        xx = x(hour)
        out.append(text(xx, height - 34, f"{hour:02d}:00", "axis", "middle"))
    out.extend([text(left, 16, "Station minus median of other three · µg/m³", "unit"),
                text((left + width - right) / 2, height - 8, "Hour starting · IST", "unit", "middle"), "</svg>"])
    return "".join(out), {
        "matched_hours": int(len(matched)),
        "possible_hours": int((end - start) / pd.Timedelta(hours=1)),
        "night_peer_difference": night,
    }


def chart_weather(joined: pd.DataFrame, rho: float) -> str:
    width,height=1040,365
    l,r,t,b=62,55,24,58
    vmax=math.ceil(joined.wind_speed_10m.quantile(.99)/2)*2
    pmax=min(250,math.ceil(joined.pm25.quantile(.98)/25)*25)
    x=lambda v:l+max(0,min(v,vmax))/vmax*(width-l-r)
    y=lambda v:t+(1-max(0,min(v,pmax))/pmax)*(height-t-b)
    out=[svg_open("Daily wind speed and PM2.5", "Each circle is one day in September through early November 2026. Weather is a modelled Open-Meteo grid average across four station coordinates. PM2.5 is the median of station daily medians.",width,height,"chart-svg")]
    for v in [0,pmax/4,pmax/2,pmax*.75,pmax]:
        yy=y(v);out.extend([line(l,yy,width-r,yy),text(l-9,yy+4,num(v),"axis","end")])
    for v in np.linspace(0,vmax,6):
        xx=x(v);out.extend([line(xx,t,xx,height-b,"vgrid"),text(xx,height-24,num(v),"axis","middle")])
    for row in joined.itertuples():
        color="#f4a261" if pd.Timestamp(row.date).month==11 else "#74c0b3" if pd.Timestamp(row.date).month==10 else "#8093ac"
        out.append(f'<circle cx="{x(float(row.wind_speed_10m)):.1f}" cy="{y(float(row.pm25)):.1f}" r="4.7" fill="{color}" opacity=".7"/>')
    out.extend([text(l,15,"PM₂.₅ · µg/m³","unit"),text(width/2,height-4,"Modelled daily mean wind speed · km/h","unit","middle"),"</svg>"])
    return "".join(out)


def station_map(stations: pd.DataFrame, station_stats: pd.DataFrame) -> str:
    width,height=720,540
    l,r,t,b=85,92,52,56
    latmin,latmax=18.94,19.27
    lonmin,lonmax=72.77,72.97
    x=lambda v:l+(v-lonmin)/(lonmax-lonmin)*(width-l-r)
    y=lambda v:t+(latmax-v)/(latmax-latmin)*(height-t-b)
    out=[svg_open("Four Mumbai air quality station locations", "Station dots positioned by latitude and longitude; this is a coordinate chart without a street or coastline basemap.",width,height,"map-svg")]
    for lon in [72.80,72.85,72.90,72.95]:
        xx=x(lon);out.extend([line(xx,t,xx,height-b,"mapgrid"),text(xx,height-24,f"{lon:.2f}°E","axis","middle")])
    for lat in [19.0,19.1,19.2]:
        yy=y(lat);out.extend([line(l,yy,width-r,yy,"mapgrid"),text(l-12,yy+4,f"{lat:.1f}°N","axis","end")])
    label_offsets={"Malad West":(-12,-22),"Shivaji Nagar":(17,-15),"Byculla":(16,15),"Borivali East":(18,20)}
    for row in stations.itertuples():
        s=short_station(row.station_name);xx=x(row.longitude);yy=y(row.latitude)
        dx,dy=label_offsets[s]
        out.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="14" fill="{COLORS[s]}" opacity=".18"/>')
        out.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="5.5" fill="{COLORS[s]}"/>')
        out.append(text(xx+dx,yy+dy,s,"maplabel","end" if dx<0 else "start"))
    out.append("</svg>")
    return "".join(out)


def build() -> dict:
    obs,stations,weather=load()
    daily=obs.groupby(["station","date"],as_index=False).pm25.agg(["median","count"]).reset_index(drop=True).rename(columns={"median":"pm25"})
    valid=daily.loc[daily["count"]>=12].copy()
    sep_oct=valid.loc[valid.date.between(pd.Timestamp("2026-09-01").date(),pd.Timestamp("2026-10-31").date())]
    aug=valid.loc[valid.date.between(pd.Timestamp("2026-08-01").date(),pd.Timestamp("2026-08-31").date())]
    octo=valid.loc[valid.date.between(pd.Timestamp("2026-10-01").date(),pd.Timestamp("2026-10-31").date())]
    aug_city=float(aug.pm25.median());oct_city=float(octo.pm25.median())
    ratio=oct_city/aug_city
    local=sep_oct.groupby("station").pm25.agg(["median","max"]).reindex(ORDER)
    coverage=obs.loc[obs.date.astype(str).between("2026-09-01","2026-11-08")].groupby("station").size().reindex(ORDER)
    total_hours=(pd.Timestamp("2026-11-09")-pd.Timestamp("2026-09-01")).days*24
    daily_chart=chart_daily(daily,"2026-09-01","2026-11-08","2026-11-08")
    coverage_chart=chart_coverage(daily,"2026-09-01","2026-11-08")
    hourly_chart,hourly=chart_hourly(obs)
    peer_chart,peer_stats=chart_peer_clock(obs)
    diwali_chart=chart_daily(daily,"2025-10-13","2025-10-27","2025-10-20")
    weather_daily=(weather.groupby(["station","date"],as_index=False).agg(
        wind_speed_10m=("wind_speed_10m","mean"), relative_humidity_2m=("relative_humidity_2m","mean"),
        precipitation=("precipitation","sum")))
    weather_city=weather_daily.groupby("date",as_index=False).agg({"wind_speed_10m":"median","relative_humidity_2m":"median","precipitation":"median"})
    pm_city=valid.groupby("date").agg(pm25=("pm25","median"),stations=("station","nunique")).reset_index()
    joined=pm_city.merge(weather_city,on="date").query("stations >= 3")
    joined=joined.loc[joined.date.between(pd.Timestamp("2026-09-01").date(),pd.Timestamp("2026-11-06").date())].copy()
    if len(joined)<45:raise ValueError("Insufficient matched weather days")
    rho=float(joined.pm25.corr(joined.wind_speed_10m,method="spearman"))
    q1,q2=joined.wind_speed_10m.quantile([1/3,2/3])
    calm=float(joined.loc[joined.wind_speed_10m<=q1,"pm25"].median())
    windy=float(joined.loc[joined.wind_speed_10m>=q2,"pm25"].median())
    weather_chart=chart_weather(joined,rho)
    map_chart=station_map(stations,local)
    missing=int(4*total_hours-coverage.sum())
    diwali25=valid.loc[valid.date==pd.Timestamp("2025-10-20").date()]
    diwali25_count=int(obs.loc[obs.date==pd.Timestamp("2025-10-20").date()].shape[0])
    diwali26_count=int(obs.loc[obs.date==pd.Timestamp("2026-11-08").date()].shape[0])
    latest=obs.target_start_ist.max()
    ledgers="".join(f'<div class="station-row"><div class="station-name"><i style="background:{COLORS[s]}"></i>{esc(FULL[s])}</div><strong>{num(local.loc[s,"median"],1)}</strong><span>median µg/m³</span><span>{int(coverage[s]):,}/{total_hours:,} hours</span></div>' for s in ORDER)
    legend="".join(f'<span><i style="background:{COLORS[s]}"></i>{esc(s)}</span>' for s in ORDER)
    p25=" · ".join(f"{esc(s)} {num(float(diwali25.loc[diwali25.station==s,'pm25'].iloc[0]),0)}" for s in ORDER if s in diwali25.station.values)
    metrics={"source_observation_hours":len(obs),"first_target_hour_ist":str(obs.target_start_ist.min()),"last_target_hour_ist":str(latest),
             "august_2026_station_day_median":aug_city,"october_2026_station_day_median":oct_city,"ratio_october_to_august":ratio,
             "sep1_nov8_missing_station_hours":missing,"sep1_nov8_possible_station_hours":4*total_hours,
             "weather_matched_days":len(joined),"daily_wind_pm25_spearman":rho,"calm_tercile_median_pm25":calm,"windy_tercile_median_pm25":windy,
             "diwali_2025_available_hours":diwali25_count,"diwali_2026_available_hours":diwali26_count,
             "peer_comparison":peer_stats}
    (DATA/"analysis_metrics.json").write_text(json.dumps(metrics,indent=2)+"\n")
    page=PAGE.replace("__DAILY_CHART__",daily_chart).replace("__COVERAGE_CHART__",coverage_chart).replace("__HOURLY_CHART__",hourly_chart).replace("__PEER_CHART__",peer_chart).replace("__WEATHER_CHART__",weather_chart).replace("__DIWALI_CHART__",diwali_chart).replace("__MAP_CHART__",map_chart)
    replacements={"__LEGEND__":legend,"__LEDGERS__":ledgers,"__OBS_COUNT__":f"{len(obs):,}","__LATEST__":latest.strftime("%d %b %Y, %H:%M IST"),
                  "__AUG_MED__":num(aug_city,1),"__OCT_MED__":num(oct_city,1),"__RATIO__":num(ratio,1),
                  "__MISSING__":f"{missing:,}","__POSSIBLE__":f"{4*total_hours:,}","__WEATHER_DAYS__":str(len(joined)),
                  "__RHO__":num(rho,2),"__CALM__":num(calm,1),"__WINDY__":num(windy,1),
                  "__MATCHED_HOURS__":str(peer_stats["matched_hours"]),"__POSSIBLE_PEER_HOURS__":str(peer_stats["possible_hours"]),
                  "__MALAD_NIGHT__":num(peer_stats["night_peer_difference"]["Malad West"],1),
                  "__BYCULLA_NIGHT__":num(peer_stats["night_peer_difference"]["Byculla"],1),
                  "__D25_COUNT__":str(diwali25_count),"__D26_COUNT__":str(diwali26_count),"__D25_VALUES__":p25}
    for key,value in replacements.items():page=page.replace(key,value)
    if "__" in page:raise ValueError("Unreplaced template token")
    (HERE/"index.html").write_text(page)
    print(f"Wrote {HERE/'index.html'} ({(HERE/'index.html').stat().st_size/1024:.1f} KiB)")
    return metrics


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="description" content="A self-contained, offline data story about PM2.5 across four Mumbai stations.">
<title>Four Breaths of Mumbai — An offline air quality atlas</title>
<style>
@font-face{font-family:DM;src:url('assets/dm-sans-latin.woff2') format('woff2');font-weight:400 800;font-display:swap}
@font-face{font-family:Space;src:url('assets/space-grotesk-latin.woff2') format('woff2');font-weight:400 700;font-display:swap}
:root{--bg:#0d1724;--surface:#142337;--line:#35506a;--text:#f4f3ee;--muted:#9db1c3;--orange:#f4a261;--red:#f26868;--mint:#74c0b3;--lav:#a0a5eb}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:DM,Arial,sans-serif;font-size:17px;line-height:1.55;overflow-x:hidden}a{color:var(--mint);text-decoration-color:var(--line);text-underline-offset:.2em}a:hover{color:var(--orange)}.wrap{width:min(1160px,calc(100% - 56px));margin:auto}.top{border-bottom:1px solid var(--line);padding:16px 0}.top .wrap,.top-right,.brand{display:flex;align-items:center;justify-content:space-between;gap:18px}.brand{justify-content:flex-start;text-transform:uppercase;font-weight:800;letter-spacing:.16em;font-size:12px}.brand-dot{height:12px;width:12px;border-radius:100%;background:var(--orange);box-shadow:16px 0 var(--red),32px 0 var(--mint),48px 0 var(--lav);margin-right:48px}.top-right{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}.top-right b{color:var(--mint)}
.hero{padding:92px 0 90px;position:relative;overflow:hidden}.hero:after{content:'';position:absolute;right:-11%;top:-170px;width:650px;height:650px;border:1px solid #294158;border-radius:50%;box-shadow:0 0 0 80px #102237,0 0 0 81px #294158,0 0 0 160px #102237,0 0 0 161px #294158;opacity:.45;pointer-events:none}.eyebrow,.kicker,.section-id,.mono{font-family:Space,monospace;text-transform:uppercase;letter-spacing:.17em;font-size:12px;font-weight:700}.eyebrow{color:var(--orange)}h1,h2,h3,p{margin-top:0}h1,h2,h3{font-family:Space,Arial,sans-serif;line-height:1.05;letter-spacing:-.055em}h1{font-size:clamp(66px,10vw,132px);max-width:1000px;margin:24px 0 30px;position:relative;z-index:1}h1 em{font-style:normal;color:var(--orange)}.hero-deck{font-size:clamp(20px,2.5vw,28px);max-width:720px;color:#cfdae2;line-height:1.35}.hero-strip{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:82px;position:relative;z-index:1}.hero-stat{padding:24px 26px 22px 0}.hero-stat+.hero-stat{border-left:1px solid var(--line);padding-left:26px}.hero-stat strong{display:block;font-family:Space;font-size:clamp(30px,4vw,49px);line-height:1.05;letter-spacing:-.06em}.hero-stat span{display:block;color:var(--muted);font-size:13px;margin-top:7px}
.chapter{border-top:1px solid var(--line);padding:100px 0 110px}.chapter-head{display:grid;grid-template-columns:210px 1fr;gap:40px}.section-id{color:var(--orange);padding-top:13px}.chapter h2{font-size:clamp(43px,6vw,76px);max-width:920px;margin:0 0 25px}.lede{font-size:clamp(19px,2vw,24px);line-height:1.45;max-width:780px;color:#d0dce4}.chapter-body{margin-left:250px}.copy{max-width:780px;color:var(--muted)}.copy strong{color:var(--text)}.chart-frame{margin:42px 0 15px;padding:24px 24px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden}.chart-frame svg{width:100%;display:block}.chart-frame .axis{fill:#acbccb;font:12px DM,Arial,sans-serif}.chart-frame .rowlabel,.chart-frame .maplabel{fill:#e6edf1;font:600 14px DM,Arial,sans-serif}.chart-frame .unit{fill:#b9cad6;font:600 13px DM,Arial,sans-serif}.chart-frame .event{fill:#f4a261;font:700 13px DM,Arial,sans-serif}.chart-frame .grid{stroke:#425772;stroke-width:1;opacity:.65}.chart-frame .vgrid,.chart-frame .mapgrid{stroke:#364a62;stroke-width:1;opacity:.48}.chart-frame .peer-zero{stroke:#d3dce4;stroke-width:1.5;opacity:.8}.chart-frame .festival-line{stroke:#f4a261;stroke-width:1.5;stroke-dasharray:5 5}.legend{display:flex;gap:24px;flex-wrap:wrap;margin:20px 0 0;font-size:13px;color:var(--muted)}.legend span{display:inline-flex;gap:8px;align-items:center}.legend i,.station-name i{display:inline-block;width:10px;height:10px;border-radius:50%;flex:0 0 10px}.caption{font-size:13px;color:var(--muted);margin-top:12px;max-width:850px}.insight{border-left:3px solid var(--orange);padding:12px 0 12px 24px;margin:28px 0 0;max-width:750px;font-size:19px;color:#e4edf1}.insight strong{color:var(--orange)}.grid-two{display:grid;grid-template-columns:1fr 1fr;gap:36px;align-items:start}.number-pair{display:flex;gap:28px;border-top:1px solid var(--line);padding-top:18px;margin:30px 0}.number-pair>div{flex:1}.number-pair b{display:block;font-family:Space;font-size:41px;letter-spacing:-.05em}.number-pair small{display:block;color:var(--muted);font-size:13px}.station-ledger{margin-top:36px}.station-row{border-top:1px solid var(--line);display:grid;grid-template-columns:minmax(160px,1fr) 85px 110px 145px;align-items:center;gap:12px;padding:15px 0;color:var(--muted);font-size:13px}.station-row:last-child{border-bottom:1px solid var(--line)}.station-row strong{color:var(--text);font-family:Space;font-size:23px}.station-name{color:var(--text);font-size:15px;font-weight:700;display:flex;align-items:center;gap:10px}.map-area{display:grid;grid-template-columns:3fr 2fr;gap:34px;align-items:center}.map-area .chart-frame{margin-top:14px}.map-note{color:var(--muted)}.callout{font-family:Space;font-size:clamp(28px,3vw,43px);line-height:1.15;letter-spacing:-.04em;color:var(--text)}.callout em{font-style:normal;color:var(--mint)}.method{background:#112034}.method .chapter-body{display:grid;grid-template-columns:1fr 1fr;gap:30px}.method-card{border-top:2px solid var(--mint);padding-top:18px;color:var(--muted)}.method-card h3{font-size:23px;color:var(--text);letter-spacing:-.03em}.method-card p{margin-bottom:0}.source-list{padding-left:22px}.source-list li{margin:9px 0}.footer{padding:60px 0 90px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}.footer b{color:var(--text)}.footer .wrap{display:flex;justify-content:space-between;gap:35px}.footer p{max-width:720px}
@media(max-width:900px){.chapter-head{grid-template-columns:1fr;gap:4px}.chapter-body{margin-left:0}.map-area{grid-template-columns:1fr}.chapter{padding:75px 0 85px}.hero{padding:70px 0}.method .chapter-body{grid-template-columns:1fr 1fr}}@media(max-width:650px){.wrap{width:min(100% - 28px,1160px)}.top-right{display:none}.hero-strip{grid-template-columns:1fr}.hero-stat+.hero-stat{border-left:0;border-top:1px solid var(--line);padding-left:0}.hero-stat{padding:15px 0}.hero{padding:58px 0}.hero-strip{margin-top:55px}.chart-frame{padding:10px 6px 7px;overflow-x:auto}.chart-frame .chart-svg,.chart-frame .coverage-svg,.chart-frame .peer-svg{min-width:650px}.chart-frame .map-svg{min-width:500px}.chapter{padding:65px 0 70px}.chapter h2{font-size:43px}.grid-two,.method .chapter-body{grid-template-columns:1fr}.station-row{grid-template-columns:1fr 75px;gap:2px 12px}.station-row>span:nth-last-child(2){display:none}.station-row>span:last-child{grid-column:1/-1}.footer .wrap{display:block}.legend{gap:9px 15px}.number-pair b{font-size:32px}}
</style></head><body>
<header class="top"><div class="wrap"><div class="brand"><span class="brand-dot"></span>Four breaths of Mumbai</div><div class="top-right"><b>Offline edition</b><span>ClimateVerse data · Google Colab build kit</span></div></div></header>
<main>
<section class="hero"><div class="wrap"><p class="eyebrow">An air quality field guide / Mumbai, India</p><h1>One city.<br><em>Four</em> breaths.</h1><p class="hero-deck">Pollution is often reported as one citywide number. Four ground stations tell a more complicated story — when the air shifts, how local the change is, and where the data itself falls silent.</p><div class="hero-strip"><div class="hero-stat"><strong>__OBS_COUNT__</strong><span>valid station-hours in the local challenge snapshot</span></div><div class="hero-stat"><strong>4</strong><span>CPCB-derived monitoring stations</span></div><div class="hero-stat"><strong>100% offline</strong><span>charts, type, data and source code bundled locally</span></div></div></div></section>

<section class="chapter" id="stations"><div class="wrap"><div class="chapter-head"><div class="section-id">01 / The network</div><div><h2>The city is not one sensor.</h2><p class="lede">The stations span the north and east of Mumbai. Their positions and pollution levels are distinct. A city average hides this geography.</p></div></div><div class="chapter-body"><div class="map-area"><div class="chart-frame">__MAP_CHART__</div><div><p class="callout">Four dots are a <em>measurement network</em>, not a complete map of exposure.</p><p class="map-note">Points use challenge station coordinates. This coordinate plot has no coastline, roads, or interpolated pollution surface. Values below are median daily PM₂.₅ in September–October 2026, on days with at least 12 valid hours.</p></div></div><div class="station-ledger">__LEDGERS__</div><p class="caption">Coverage counts are for 1 September–8 November 2026; denominator is the possible 24 hours per station per day. Observations are not population-weighted.</p></div></div></section>

<section class="chapter" id="season"><div class="wrap"><div class="chapter-head"><div class="section-id">02 / The shift</div><div><h2>Then the baseline rose.</h2><p class="lede">The September–November 2026 series is noisy, but the dry-season transition appears in all four monitors. The shift is larger than a single exceptional day.</p></div></div><div class="chapter-body"><div class="number-pair"><div><b>__AUG_MED__</b><small>August station-day median · µg/m³</small></div><div><b>__OCT_MED__</b><small>October station-day median · µg/m³</small></div></div><div class="chart-frame">__DAILY_CHART__</div><div class="legend">__LEGEND__</div><p class="caption">Daily medians of valid hourly readings; a line stops on days with fewer than 12 readings. The chart caps the tallest outliers for readability. The shaded interpretation is descriptive, not a causal attribution.</p><p class="insight">Across station-days, the October median was <strong>__RATIO__×</strong> the August median. A forecast or public message that assumes August conditions would miss this level change.</p></div></div></section>

<section class="chapter" id="gaps"><div class="wrap"><div class="chapter-head"><div class="section-id">03 / The silence</div><div><h2>Missing hours change the story.</h2><p class="lede">A dramatic daily number can come from only a handful of reporting hours. Before comparing dates, first ask whether each monitor was actually present.</p></div></div><div class="chapter-body"><div class="chart-frame">__COVERAGE_CHART__</div><p class="caption">Each cell is one station-day. Full color means all 24 hours observed; faint color means fewer; gray means zero. The hour is labelled by its start in India Standard Time.</p><p class="insight"><strong>__MISSING__ of __POSSIBLE__</strong> possible station-hours are absent between 1 September and 8 November. The data gap is part of the finding, not an invitation to draw a smooth line through it.</p></div></div></section>

<section class="chapter" id="clock"><div class="wrap"><div class="chapter-head"><div class="section-id">04 / The clock</div><div><h2>Every station has a daily rhythm.</h2><p class="lede">The same hour does not mean the same concentration everywhere. These profiles summarize October 2026, when the seasonal level was closer to the November question.</p></div></div><div class="chapter-body"><div class="chart-frame">__HOURLY_CHART__</div><div class="legend">__LEGEND__</div><p class="caption">Median concentration for each station and local hour across 1–31 October 2026. This is a descriptive profile, not a forecast. It does not imply a repeating day when weather or emissions change.</p></div></div></section>

<section class="chapter" id="peer-clock"><div class="wrap"><div class="chapter-head"><div class="section-id">05 / The difference</div><div><h2>What does one station see that the others miss?</h2><p class="lede">At each hour, subtract the median of the other three stations from one station’s reading. This removes the movement shared at that moment and reveals a local fingerprint.</p></div></div><div class="chapter-body"><div class="chart-frame">__PEER_CHART__</div><p class="caption">The line is the median same-hour difference across 1 October–6 November 2026. Only hours when all four stations reported are used: __MATCHED_HOURS__ of __POSSIBLE_PEER_HOURS__ possible. Positive means above the other three; negative means below. “Night” is 20:00–07:59 IST. Each hour bin contains at least 16 matched observations.</p><p class="insight">Across matched night hours, Malad West was <strong>+__MALAD_NIGHT__ µg/m³</strong> above its three-station peer median; Byculla was <strong>__BYCULLA_NIGHT__ µg/m³</strong> below. A citywide number can obscure both differences.</p><p class="copy">This is a comparison among four monitors, not a map of neighborhood exposure. Differences may also reflect monitor behavior. The pattern points to where more local investigation could be useful.</p></div></div></section>

<section class="chapter" id="weather"><div class="wrap"><div class="chapter-head"><div class="section-id">06 / A second lens</div><div><h2>Weather helps frame the question.</h2><p class="lede">ClimateVerse lists Open-Meteo’s historical weather API as a challenge resource. We cached modelled weather at the four station coordinates and paired it with days that have at least three reporting monitors.</p></div></div><div class="chapter-body"><div class="chart-frame">__WEATHER_CHART__</div><p class="caption">__WEATHER_DAYS__ matched days, 1 September–6 November 2026. Weather: median of four modelled daily mean wind speeds, not on-site anemometer readings. PM₂.₅: median of station daily medians with ≥12 hours per station. September gray, October teal, November orange.</p><div class="grid-two"><p class="insight" style="margin-top:20px">The simple rank correlation is <strong>__RHO__</strong>. This is an association across changing seasons; it cannot identify what caused pollution to rise.</p><div class="number-pair"><div><b>__CALM__</b><small>PM₂.₅ on calmest third of days</small></div><div><b>__WINDY__</b><small>PM₂.₅ on windiest third of days</small></div></div></div><p class="copy">Open-Meteo serves a grid-cell model. Its wind can differ from observed street-level wind. This chart intentionally makes no health threshold claim and does not convert PM₂.₅ to AQI.</p></div></div></section>

<section class="chapter" id="festival"><div class="wrap"><div class="chapter-head"><div class="section-id">07 / The festival</div><div><h2>One festival, incomplete evidence.</h2><p class="lede">The 2025 Diwali window shows how quickly pollution can change, but also why a single festival day should not become a permanent forecasting rule.</p></div></div><div class="chapter-body"><div class="chart-frame">__DIWALI_CHART__</div><div class="legend">__LEGEND__</div><p class="caption">2025 Diwali was 20 October. After quality filtering, the 2025 festival date has __D25_COUNT__ of 96 possible station-hours; the 2026 date, 8 November, has __D26_COUNT__ in this challenge snapshot. Daily medians omit station-days with fewer than 12 readings. Time variation is not proof that fireworks alone caused the change.</p><p class="copy">On 20 October 2025, available station-day medians were __D25_VALUES__ µg/m³. The 2026 festival’s lack of coverage prevents a like-for-like claim here.</p></div></div></section>

<section class="chapter method" id="method"><div class="wrap"><div class="chapter-head"><div class="section-id">08 / Field notes</div><div><h2>Read the signal. Keep the caveats.</h2><p class="lede">A useful air-quality product should show place, time and measurement quality together. This page is a frozen evidence snapshot for conversation and review.</p></div></div><div class="chapter-body"><div class="method-card"><h3>What the page measures</h3><p>Hourly PM₂.₅ concentration in µg/m³ from the four Zindi challenge stations. The source timestamp is the end of an hour; every analysis shifts it back one hour. Values flagged above 1,000 µg/m³ are removed. Most charts summarize observed hourly values using medians.</p></div><div class="method-card"><h3>What the page does not infer</h3><p>No neighborhood-wide interpolation, no individual exposure estimate, no causal Diwali effect, and no claim that modelled weather is ground truth. Gaps remain visible. The latest cached target hour is __LATEST__.</p></div><div class="method-card"><h3>Source trail</h3><ul class="source-list"><li><a href="https://zindi.world/competitions/google-mumbai-data-challenge/data">Google Mumbai Data Challenge / CPCB via OpenAQ</a> · CC BY-SA 4.0.</li><li><a href="https://india.climateverse.net/dataverse/google-air-quality-forecasting-challenge">ClimateVerse challenge catalog</a> and <a href="https://india.climateverse.net/dataset.xhtml?persistentId=doi:10.71646/XXOBKO">Open-Meteo dataset record</a> · dataset discovery, provider attribution and caveats.</li><li><a href="https://open-meteo.com/en/docs/historical-weather-api">Open-Meteo historical weather API</a> · modelled grid-cell weather, CC BY 4.0 per ClimateVerse record.</li><li><a href="https://saiindia.gov.in/cen/mumbai/en/page-cen-mumbai-holiday-list">Mumbai 2025 holiday list</a> and <a href="https://www.indiapost.gov.in/holidays-list">India Post 2026 holiday list</a> · Diwali dates.</li></ul></div><div class="method-card"><h3>Offline construction</h3><p>The finished page needs no network, JavaScript, map tiles or API key. The Python build reads cached CSV snapshots and writes one HTML file with inline SVG charts. Google Fonts are bundled as local WOFF2 files; a Google Colab notebook includes data checks and rebuilds the page from the same cached folder.</p></div></div></div></section>
</main><footer class="footer"><div class="wrap"><p><b>Four breaths of Mumbai</b><br>A static, inspectable data story for the Google Mumbai Data Challenge creative submission. Built from locally cached data; charts are generated from source code in this folder.</p><p>Designed to travel offline.<br>Open <b>index.html</b> directly in a browser.</p></div></footer>
</body></html>'''


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-cache",action="store_true",help="Snapshot parent air_quality/input challenge files into this project")
    parser.add_argument("--fetch-weather",action="store_true",help="Fetch and freeze ClimateVerse-listed Open-Meteo weather; needs network")
    args=parser.parse_args()
    if args.prepare_cache:cache_challenge_data()
    if args.fetch_weather:fetch_weather()
    print(json.dumps(build(),indent=2))
