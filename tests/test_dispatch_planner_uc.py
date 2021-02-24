import pandas as pd
import numpy as np
from pandas._testing import assert_frame_equal
from nempy.bidding_model import planner


def test_start_off_with_initial_down_time_of_zero():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=60, min_down_time=120, initial_state=0, initial_up_time=0,
                                       initial_down_time=0)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [0.0, 0.0, 100.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_off_with_initial_down_time_less_than_min_down_time():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=60, min_down_time=120, initial_state=0, initial_up_time=0,
                                       initial_down_time=60)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [0.0, 100.0, 100.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_off_with_initial_down_time_equal_to_min_down_time():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=60, min_down_time=120, initial_state=0, initial_up_time=0,
                                       initial_down_time=120)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [100.0, 100.0, 100.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_on_with_initial_up_time_of_zero():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0, cost=1000.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=120, min_down_time=120, initial_state=1, initial_up_time=0,
                                       initial_down_time=0)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [50.0, 50.0, 0.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_on_with_initial_up_time_less_than_min_up_time():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0, cost=1000.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=120, min_down_time=120, initial_state=1, initial_up_time=60,
                                       initial_down_time=0)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [50.0, 0.0, 0.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_on_with_initial_up_time_equal_to_up_time():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 500, num=101),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0, cost=1000.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=120, min_down_time=120, initial_state=1, initial_up_time=120,
                                       initial_down_time=0)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [0.0, 0.0, 0.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)


def test_start_on_with_initial_up_time_less_than_min_up_time_check_stays_on():
    historical_data = pd.DataFrame({
        'interval': np.linspace(0, 100, num=101).astype(int),
        'nsw-energy': np.linspace(0, 100, num=101).astype(int),
        'nsw-demand': np.linspace(0, 500, num=101),
        'nsw-energy-fleet-dispatch': np.zeros(101)})

    forward_data = pd.DataFrame({
        'interval': [0, 1, 2],
        'nsw-demand': [200, 200, 200]})

    p = planner.DispatchPlanner(dispatch_interval=60, historical_data=historical_data, forward_data=forward_data,
                                demand_delta_steps=10)

    p.add_unit('gen', 'nsw')
    p.add_unit_to_market_flow('gen', 100.0)
    p.add_generator('gen', 100.0, cost=-500.0)
    p.add_unit_minimum_operating_level('gen', min_loading=50.0, shutdown_ramp_rate=100.0, start_up_ramp_rate=100.0,
                                       min_up_time=120, min_down_time=0, initial_state=1, initial_up_time=60,
                                       initial_down_time=0)

    p.add_regional_market('nsw', 'energy')

    p.optimise()

    dispatch = p.get_unit_dispatch('gen')

    expect_dispatch = pd.DataFrame({
        'interval': [0, 1, 2],
        'net_dispatch': [100.0, 100.0, 100.0]
    })

    assert_frame_equal(expect_dispatch, dispatch)