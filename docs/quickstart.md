# Quickstart

All commands use a virtual environment, nothing global. Either install
straight from GitHub:

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install "mktsim[gui] @ git+https://github.com/ASH-SuperUser/mktsim.git"
```

or clone for development (from the repo root):

```powershell
git clone https://github.com/ASH-SuperUser/mktsim.git
cd mktsim
py -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[gui,test]"
```

Full options in the README's [Installation](https://github.com/ASH-SuperUser/mktsim#installation) guide.

## First simulation (Python)

```python
from mktsim import basic_id_sim_1

path = basic_id_sim_1(375, 100.0, profitability=0.5, seed=1)
print(f"ticks={len(path)} start={path[0]:.2f} end={path[-1]:.2f}")
# ticks=375 start=100.00 end=97.95
```

## First simulation (CLI → CSV)

```powershell
mktsim --algo basic_id_sim_1 --param nums=375 --param initial_price=100 --param seed=1 --format ohlcv --bars 75 --out day.csv
```

`day.csv` then holds `bar,open,high,low,close,volume` (75 rows).

## First look (GUI)

```powershell
mktsim-gui
```

Select `basic_interaday.basic_id_sim_1`, press **Generate & Plot**.
