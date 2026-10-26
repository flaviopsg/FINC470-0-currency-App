# Bilateral Real & Nominal Exchange Rate Analyzer

A Streamlit application designed to fetch, align, and analyze Real Exchange Rates (RER) and Nominal Exchange Rates ($S(t)$) between IMF member countries and the Euro Area using the official **IMF SDMX 3.0 REST API**.

---

## Economic Definitions & Direction Formulas

### 1. Raw IMF Input Data
The IMF SDMX 3.0 API returns monthly Consumer Price Index ($CPI$) series and period-average exchange rates against the US Dollar ($USD$):
* $E_1(t)$: Local Currency Units of Country 1 per 1 USD ($LCU_1 / USD$).
* $E_2(t)$: Local Currency Units of Country 2 per 1 USD ($LCU_2 / USD$).
* $P_1(t)$: CPI of Country 1.
* $P_2(t)$: CPI of Country 2.

### 2. Nominal Bilateral Exchange Rate Conversion
The app requires $S(t)$ expressed as **units of Country 2 currency per 1 unit of Country 1 currency** ($LCU_2 / LCU_1$):

$$S(t) = \frac{E_2(t)}{E_1(t)} = \frac{LCU_2 / USD}{LCU_1 / USD} = \frac{LCU_2}{LCU_1}$$

**Edge Case Handling**:
* **Country 1 is United States**: $E_1(t) = 1.0 \implies S(t) = E_2(t)$.
* **Country 2 is United States**: $E_2(t) = 1.0 \implies S(t) = \frac{1.0}{E_1(t)}$.
* **Same Country or Same Currency Pair**: $S(t) = 1.0$.

### 3. Real Exchange Rate ($RER$) and Real Index
* **Real Exchange Rate**:

$$RER(t) = S(t) \times \frac{P_1(t)}{P_2(t)}$$

* **Sample Baseline ($RER^*$)**: Calculated as the arithmetic mean of $RER(t)$ over all valid overlapping observations within the user-selected date window:

$$RER^* = \frac{1}{N} \sum_{t \in \text{Sample}} RER(t)$$

* **Real Index ($100 \times RER(t) / RER^*$)**: Recomputed dynamically whenever the date slider changes:

$$\text{Real Index}(t) = 100 \times \frac{RER(t)}{RER^*}$$

---

## Data Source & IMF Series Keys

Data is sourced dynamically via the **IMF SDMX 3.0 API** at `https://api.imf.org/external/sdmx/3.0`.

* **Monthly CPI Key**: `{ISO3}.CPI._T.IX.M`
* **Monthly FX Key**: `{ISO3}.XDC_USD.PA_RT.M`
* **Euro Area Code**: `G163`

---

## Installation & Running

### 1. Prerequisites
Ensure you have **Python 3.12** installed on your system.

### 2. Environment Setup
```bash
# Create a virtual environment
python3.12 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
