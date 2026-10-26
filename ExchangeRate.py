"""
Real and Nominal Exchange Rate Analyzer using IMF SDMX 3.0 API.

This application fetches monthly CPI and Exchange Rate series from the IMF,
derives bilateral nominal and real exchange rate indices, and presents them
through an interactive Streamlit dashboard.
"""

from typing import Dict, Tuple, Optional
import datetime
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ==============================================================================
# CONFIGURATION & CONSTANTS
# ==============================================================================

APP_TITLE = "Bilateral Real & Nominal Exchange Rate Analyzer"
IMF_API_BASE = "https://api.imf.org/external/sdmx/3.0"
DATA_START_YEAR = 1976
CACHE_TTL_SECONDS = 86400  # 24 hours

# IMF Dataflows / Indicators
# CPI Series Key Template: {ISO3}.CPI._T.IX.M
# Exchange Rate Template:   {ISO3}.XDC_USD.PA_RT.M (Local Currency Units per 1 USD, Period Average)
CPI_METRIC_CODE = "CPI._T.IX.M"
FX_METRIC_CODE = "XDC_USD.PA_RT.M"

# Hardcoded mapping of Country / Region Name -> ISO3 / IMF Entity Code
# Euro Area is designated as G163 in IMF SDMX series
COUNTRY_MAP: Dict[str, str] = {
    "United States": "USA",
    "Euro Area": "G163",
    "United Kingdom": "GBR",
    "Japan": "JPN",
    "Canada": "CAN",
    "Switzerland": "CHE",
    "Australia": "AUS",
    "New Zealand": "NZL",
    "China": "CHN",
    "Korea, Republic of": "KOR",
    "Brazil": "BRA",
    "Mexico": "MEX",
    "India": "IND",
    "South Africa": "ZAF",
    "Sweden": "SWE",
    "Norway": "NOR",
    "Denmark": "DNK",
    "Poland": "POL",
    "Turkey": "TUR",
    "Singapore": "SGP",
}

# Currency Symbols / Names for display axis labels
CURRENCY_NAMES: Dict[str, str] = {
    "USA": "USD",
    "G163": "EUR",
    "GBR": "GBP",
    "JPN": "JPY",
    "CAN": "CAD",
    "CHE": "CHF",
    "AUS": "AUD",
    "NZL": "NZD",
    "CHN": "CNY",
    "KOR": "KRW",
    "BRA": "BRL",
    "MEX": "MXN",
    "IND": "INR",
    "ZAF": "ZAR",
    "SWE": "SEK",
    "NOR": "NOK",
    "DNK": "DKK",
    "POL": "PLN",
    "TUR": "TRY",
    "SGP": "SGD",
}

DEFAULT_COUNTRY_1 = "United States"
DEFAULT_COUNTRY_2 = "Euro Area"


# ==============================================================================
# DATA FETCHING LAYER (IMF SDMX 3.0 API)
# ==============================================================================

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_imf_series(entity_code: str, metric_code: str, start_year: int = DATA_START_YEAR) -> pd.Series:
    """
    Fetch a monthly macroeconomic series from the IMF SDMX 3.0 REST API.

    Parameters
    ----------
    entity_code : str
        The 3-letter ISO code or IMF region identifier (e.g., 'USA', 'G163').
    metric_code : str
        The indicator series identifier (e.g., 'CPI._T.IX.M' or 'XDC_USD.PA_RT.M').
    start_year : int
        Start year for data retrieval.

    Returns
    -------
    pd.Series
        A pandas Series indexed by Month Period (`PeriodIndex` freq='M') containing float data.
        Returns an empty Series on network error, parse error, or missing data.
    """
    # Build endpoint query according to IMF SDMX 3.0 structure
    # Requesting compact SDMX-JSON or CSV format
    url = f"{IMF_API_BASE}/data/IMF.STA,CPI_XDC/{entity_code}.{metric_code}"
    params = {
        "startPeriod": f"{start_year}-01",
        "format": "csv"  # CSV format is resilient and lightweight to parse in pandas
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Streamlit Macro Analytics Tool)",
        "Accept": "text/csv, application/json;q=0.9"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=12)
        if response.status_code == 200 and len(response.text.strip()) > 0:
            # Parse CSV payload directly from response string
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            
            # Normalize column names to uppercase for robust matching
            df.columns = [c.upper() for c in df.columns]
            
            # Look for standard SDMX time and value columns
            time_col = next((c for c in df.columns if c in ["TIME_PERIOD", "TIME", "PERIOD"]), None)
            val_col = next((c for c in df.columns if c in ["OBS_VALUE", "VALUE", "VAL"]), None)
            
            if time_col and val_col:
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
                df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
                df = df.dropna(subset=[time_col, val_col])
                
                # Convert to monthly PeriodIndex
                df["MONTH"] = df[time_col].dt.to_period("M")
                series = df.groupby("MONTH")[val_col].first().sort_index()
                return series
    except Exception:
        # Fallback handling: return empty series on any HTTP or parsing exception
        pass
        
    return pd.Series(dtype=float)


def load_country_data(iso_code: str) -> Tuple[pd.Series, pd.Series]:
    """
    Load CPI and Exchange Rate against USD for a given country code.

    Parameters
    ----------
    iso_code : str
        ISO3 or IMF region code.

    Returns
    -------
    Tuple[pd.Series, pd.Series]
        (CPI_Series, FX_Series)
    """
    cpi_series = fetch_imf_series(iso_code, CPI_METRIC_CODE)
    
    # Handle US domestic exchange rate explicitly: 1 USD = 1 USD
    if iso_code == "USA":
        if not cpi_series.empty:
            fx_series = pd.Series(1.0, index=cpi_series.index)
        else:
            # Synthetic monthly timeline if CPI is unavailable
            idx = pd.period_range(start=f"{DATA_START_YEAR}-01", end=pd.Timestamp.now().to_period("M"), freq="M")
            fx_series = pd.Series(1.0, index=idx)
    else:
        fx_series = fetch_imf_series(iso_code, FX_METRIC_CODE)

    return cpi_series, fx_series


# ==============================================================================
# ECONOMIC COMPUTATIONS & CONVERSIONS
# ==============================================================================

def compute_exchange_and_rer(
    cpi1: pd.Series, 
    fx1: pd.Series, 
    cpi2: pd.Series, 
    fx2: pd.Series,
    iso1: str,
    iso2: str
) -> pd.DataFrame:
    """
    Align macroeconomic series and calculate bilateral Nominal Exchange Rate S(t)
    and Real Exchange Rate RER(t).

    FORMULA & DIRECTION:
    -------------------
    IMF FX series return E_i(t) = Local Currency Units of Country i per 1 USD.
      - E1(t) = LCU1 / USD
      - E2(t) = LCU2 / USD

    We require S(t) defined as:
      S(t) = units of Country 2 currency per 1 unit of Country 1 currency (LCU2 / LCU1).

    Derivation:
      S(t) = E2(t) / E1(t)  = (LCU2 / USD) / (LCU1 / USD) = LCU2 / LCU1

    Special Cases:
      - If Country 1 is USA: E1(t) = 1.0 -> S(t) = E2(t)
      - If Country 2 is USA: E2(t) = 1.0 -> S(t) = 1.0 / E1(t)
      - If Country 1 == Country 2: S(t) = 1.0

    Real Exchange Rate:
      RER(t) = S(t) * [ P1(t) / P2(t) ]
      where P1(t) = CPI of Country 1, P2(t) = CPI of Country 2.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by Month, containing P1, P2, FX1_USD, FX2_USD, S_t, RER_t.
    """
    # Align all four series into a unified monthly DataFrame
    df = pd.DataFrame({
        "P1": cpi1,
        "FX1_USD": fx1,
        "P2": cpi2,
        "FX2_USD": fx2
    }).dropna()

    if df.empty:
        return pd.DataFrame()

    # Handle same-currency or same-country pair
    if iso1 == iso2:
        df["S_t"] = 1.0
    else:
        # Prevent division by zero
        df = df[(df["FX1_USD"] > 0) & (df["FX2_USD"] > 0) & (df["P2"] > 0)]
        df["S_t"] = df["FX2_USD"] / df["FX1_USD"]

    # Compute Real Exchange Rate
    df["RER_t"] = df["S_t"] * (df["P1"] / df["P2"])

    return df


# ==============================================================================
# UI COMPONENTS & PRESENTATION LAYER
# ==============================================================================

def apply_custom_styles():
    """Inject custom CSS styling for dark/light mode compatibility."""
    st.markdown("""
        <style>
        .main-header {
            font-size: 2.1rem;
            font-weight: 700;
            color: #1E293B;
            margin-bottom: 0.2rem;
        }
        .sub-header {
            font-size: 1.0rem;
            color: #64748B;
            margin-bottom: 1.5rem;
        }
        .metric-card {
            background-color: rgba(241, 245, 249, 0.5);
            border: 1px solid rgba(226, 232, 240, 0.8);
            border-radius: 8px;
            padding: 12px 16px;
            text-align: center;
        }
        .metric-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #0F172A;
        }
        .metric-label {
            font-size: 0.82rem;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        </style>
    """, unsafe_allow_html=True)


def build_charts(df_sub: pd.DataFrame, curr1: str, curr2: str, view_mode: str) -> go.Figure:
    """Construct responsive interactive Plotly charts."""
    dates = df_sub.index.to_timestamp()
    
    if view_mode == "Real":
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=df_sub["Real_Index"],
            mode="lines", name="Real Index (Base = 100)",
            line=dict(color="#2563EB", width=2.5),
            hovertemplate="<b>Date</b>: %{x|%b %Y}<br><b>Real Index</b>: %{y:.2f}<extra></extra>"
        ))
        fig.add_hline(y=100, line_dash="dash", line_color="#EF4444", annotation_text="Sample Avg = 100", annotation_position="bottom right")
        fig.update_layout(yaxis_title="Real Index (Sample Avg = 100)", title="Real Exchange Rate Index")

    elif view_mode == "Nominal":
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=df_sub["S_t"],
            mode="lines", name=f"Nominal S(t) [{curr2}/{curr1}]",
            line=dict(color="#059669", width=2.5),
            hovertemplate="<b>Date</b>: %{x|%b %Y}<br><b>Nominal S(t)</b>: %{y:.4f}<extra></extra>"
        ))
        fig.update_layout(yaxis_title=f"Nominal S(t) ({curr2} per 1 {curr1})", title="Nominal Exchange Rate")

    else:  # Both
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(go.Scatter(
            x=dates, y=df_sub["Real_Index"],
            mode="lines", name="Real Index (Base=100)",
            line=dict(color="#2563EB", width=2.5),
            hovertemplate="<b>Date</b>: %{x|%b %Y}<br><b>Real Index</b>: %{y:.2f}<extra></extra>"
        ), secondary_y=False)

        fig.add_trace(go.Scatter(
            x=dates, y=df_sub["S_t"],
            mode="lines", name=f"Nominal S(t) [{curr2}/{curr1}]",
            line=dict(color="#059669", width=2.5, dash="solid"),
            hovertemplate="<b>Date</b>: %{x|%b %Y}<br><b>Nominal S(t)</b>: %{y:.4f}<extra></extra>"
        ), secondary_y=True)

        fig.add_hline(y=100, line_dash="dash", line_color="#93C5FD", secondary_y=False)

        fig.update_layout(title=f"Real Index vs. Nominal Exchange Rate ({curr2} per {curr1})")
        fig.update_yaxes(title_text="Real Index (Base = 100)", titlefont=dict(color="#2563EB"), tickfont=dict(color="#2563EB"), secondary_y=False)
        fig.update_yaxes(title_text=f"Nominal S(t) [{curr2} per 1 {curr1}]", titlefont=dict(color="#059669"), tickfont=dict(color="#059669"), secondary_y=True)

    fig.update_layout(
        template="plotly_white",
        height=520,
        hovermode="x unified",
        margin=dict(l=40, r=40, t=60, b=40),
        xaxis=dict(
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(count=5, label="5y", step="year", stepmode="backward"),
                    dict(count=10, label="10y", step="year", stepmode="backward"),
                    dict(step="all", label="Max")
                ])
            ),
            rangeslider=dict(visible=True),
            type="date"
        )
    )
    return fig


# ==============================================================================
# MAIN APPLICATION LOGIC
# ==============================================================================

def main():
    st.set_page_config(
        page_title="IMF Exchange Rate & RER Analytics",
        page_icon="📈",
        layout="wide"
    )
    
    apply_custom_styles()

    st.markdown('<div class="main-header">Bilateral Real & Nominal Exchange Rate Analyzer</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Macroeconomic comparison using International Monetary Fund (IMF) SDMX 3.0 API time-series</div>', unsafe_allow_html=True)

    # Sidebar Controls
    st.sidebar.header("Parameters & Configuration")

    c1_name = st.sidebar.selectbox("Country 1 (Base Country)", list(COUNTRY_MAP.keys()), index=list(COUNTRY_MAP.keys()).index(DEFAULT_COUNTRY_1))
    c2_name = st.sidebar.selectbox("Country 2 (Reference Country)", list(COUNTRY_MAP.keys()), index=list(COUNTRY_MAP.keys()).index(DEFAULT_COUNTRY_2))

    iso1, iso2 = COUNTRY_MAP[c1_name], COUNTRY_MAP[c2_name]
    curr1, curr2 = CURRENCY_NAMES.get(iso1, "LCU1"), CURRENCY_NAMES.get(iso2, "LCU2")

    view_mode = st.sidebar.radio("Chart View Mode", ["Real", "Nominal", "Both"], index=0)

    # Data Retrieval & Processing
    with st.spinner("Fetching data from IMF SDMX 3.0 API..."):
        cpi1, fx1 = load_country_data(iso1)
        cpi2, fx2 = load_country_data(iso2)

    if cpi1.empty or cpi2.empty or fx1.empty or fx2.empty:
        st.error(
            f"Unable to retrieve complete IMF time series for **{c1_name}** or **{c2_name}**. "
            "The IMF SDMX 3.0 API may be experiencing temporary connectivity issues or missing series for the selected entities."
        )
        st.info("Tip: Try selecting different major economies such as the United States, Euro Area, or United Kingdom.")
        return

    # Compute derived economic series
    df_calc = compute_exchange_and_rer(cpi1, fx1, cpi2, fx2, iso1, iso2)

    if df_calc.empty:
        st.warning("No overlapping monthly observations found between the CPI and Exchange Rate series of the selected countries.")
        return

    # Date Range Filter in Sidebar based on available overlapping months
    available_months = df_calc.index.tolist()
    min_date = available_months[0].to_timestamp()
    max_date = available_months[-1].to_timestamp()

    st.sidebar.subheader("Sample Window")
    start_date, end_date = st.sidebar.slider(
        "Select Date Range",
        min_value=min_date.date(),
        max_value=max_date.date(),
        value=(min_date.date(), max_date.date()),
        format="YYYY-MM"
    )

    # Filter data window
    start_period = pd.Period(start_date, freq="M")
    end_period = pd.Period(end_date, freq="M")
    df_sub = df_calc.loc[start_period:end_period].copy()

    valid_months = len(df_sub)
    if valid_months < 2:
        st.error("The selected date range contains fewer than 2 valid overlapping observations. Please expand the date slider.")
        return

    # Dynamic RER* Calculation over chosen window
    rer_star = df_sub["RER_t"].mean()
    df_sub["RER_Star"] = rer_star
    df_sub["Real_Index"] = 100.0 * (df_sub["RER_t"] / rer_star)

    # Summary Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Sample Start</div><div class="metric-value">{df_sub.index[0]}</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Sample End</div><div class="metric-value">{df_sub.index[-1]}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Valid Months</div><div class="metric-value">{valid_months}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div class="metric-label">RER* (Mean)</div><div class="metric-value">{rer_star:.4f}</div></div>', unsafe_allow_html=True)

    st.write("")

    # Main Chart Display
    fig = build_charts(df_sub, curr1, curr2, view_mode)
    st.plotly_chart(fig, use_container_width=True)

    # Data Export Section
    st.subheader("Data Export & Inspection")
    
    export_df = df_sub.reset_index()
    export_df["Date"] = export_df["MONTH"].dt.strftime("%Y-%m")
    export_df = export_df[["Date", "P1", "P2", "FX1_USD", "FX2_USD", "S_t", "RER_t", "RER_Star", "Real_Index"]]
    export_df.columns = [
        "Date", 
        f"P1_CPI ({c1_name})", 
        f"P2_CPI ({c2_name})", 
        f"FX1_USD ({curr1}/USD)", 
        f"FX2_USD ({curr2}/USD)", 
        f"Nominal_S_t ({curr2}/{curr1})", 
        "RER_t", 
        "RER_Star_SampleAvg", 
        "Real_Index_Base100"
    ]

    csv_data = export_df.to_csv(index=False).encode('utf-8')
    filename = f"IMF_RER_{iso1}_{iso2}_{df_sub.index[0]}_to_{df_sub.index[-1]}.csv"

    st.download_button(
        label="📥 Download CSV Dataset",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        help="Download the filtered time series with all intermediate calculations as a CSV file."
    )

    with st.expander("View Data Table Summary"):
        st.dataframe(export_df.style.format({
            f"P1_CPI ({c1_name})": "{:.2f}",
            f"P2_CPI ({c2_name})": "{:.2f}",
            f"FX1_USD ({curr1}/USD)": "{:.4f}",
            f"FX2_USD ({curr2}/USD)": "{:.4f}",
            f"Nominal_S_t ({curr2}/{curr1})": "{:.4f}",
            "RER_t": "{:.4f}",
            "RER_Star_SampleAvg": "{:.4f}",
            "Real_Index_Base100": "{:.2f}"
        }), use_container_width=True)


if __name__ == "__main__":
    main()
