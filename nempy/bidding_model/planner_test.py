import pandas as pd
from nempy.bidding_model import planner
import matplotlib.pyplot as plt

from nempy.bidding_model.regional_demand import get_regional_demand
from nempy.bidding_model.interconnector_limits import get_interconnector_limits
from nempy.bidding_model.regional_price import get_regional_prices

price = get_regional_prices('2019/01/01 00:00:00', '2020/01/01 00:00:00')
demand = get_regional_demand('2019/01/01 00:00:00', '2020/01/01 00:00:00')
inter_limits = get_interconnector_limits('2019/01/01 00:00:00', '2020/01/01 00:00:00')

price['SETTLEMENTDATE'] = pd.to_datetime(price['SETTLEMENTDATE'])
data = pd.merge(demand, price, on='SETTLEMENTDATE')

for col in data.columns:
    if col != 'SETTLEMENTDATE':
        data[col] = pd.to_numeric(data[col])

forward_data = data[data['SETTLEMENTDATE'] < '2020/01/01 00:00:00']
forward_data = forward_data[forward_data['SETTLEMENTDATE'] >= '2019/12/01 00:00:00'].reset_index(drop=True)

data = data.rename(columns={'SETTLEMENTDATE': 'interval'})
data['interval'] = pd.to_datetime(data['interval'])
data = data[data['interval'].dt.minute.isin([0, 30])]
data = data.reset_index(drop=True)
data['interval'] = data.index

forward_data = forward_data.rename(columns={'SETTLEMENTDATE': 'interval'})
forward_data['interval'] = pd.to_datetime(forward_data['interval'])
forward_data = forward_data[forward_data['interval'].dt.minute.isin([0, 30])]
forward_data = forward_data.reset_index(drop=True)
forward_data['interval'] = forward_data.index

p = planner.DispatchPlanner(30.0, historical_data=data, forward_data=forward_data)
p.add_regional_market('nsw', 'energy')
p.add_unit('stor', 'nsw')
p.add_market_to_unit_flow('stor', 1000.0)
p.add_unit_to_market_flow('stor', 1000.0)
p.add_storage('stor', mwh=1000.0, initial_mwh=500.0, output_capacity=1000.0, output_efficiency=0.9,
              input_capacity=1000.0, input_efficiency=0.9)
p.optimise()
dispatch = p.get_dispatch()

price_forecast = p.get_nominal_price_forecast('nsw', 'energy')

fig, axs = plt.subplots(1, 1, tight_layout=True)
axs.scatter(dispatch['interval'], dispatch['dispatch'], color='blue', label='dispatch')
ax2=axs.twinx()
ax2.scatter(price_forecast['interval'], price_forecast[0], color='red', label='price')
axs.legend()
fig.tight_layout()

fig2, axs2 = plt.subplots(1, 1, tight_layout=True)
axs2.scatter(dispatch['interval'], dispatch['storage'], color='blue', label='storage level')
ax22=axs2.twinx()
ax22.scatter(price_forecast['interval'], price_forecast[0], color='red', label='price')
axs2.legend()
fig.tight_layout()

plt.show()