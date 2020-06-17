import sqlite3
import pandas as pd
from pandas._testing import assert_frame_equal
import numpy as np
import os.path
from datetime import datetime, timedelta
import random
from nempy import historical_spot_market_inputs as hi, markets, helper_functions as hf
from time import time


# Define a set of random intervals to test
def get_test_intervals():
    start_time = datetime(year=2019, month=1, day=2, hour=0, minute=0)
    end_time = datetime(year=2019, month=2, day=1, hour=0, minute=0)
    difference = end_time - start_time
    difference_in_5_min_intervals = difference.days * 12 * 24
    random.seed(1)
    intervals = random.sample(range(1, difference_in_5_min_intervals), 100)
    times = [start_time + timedelta(minutes=5 * i) for i in intervals]
    times_formatted = [t.isoformat().replace('T', ' ').replace('-', '/') for t in times]
    return times_formatted


def test_setup():
    # Setup the database of historical inputs to test the Spot market class with.
    if not os.path.isfile('test_files/historical_inputs.db'):
        # Create a database for the require inputs.
        con = sqlite3.connect('test_files/historical_inputs.db')
        inputs_manager = hi.DBManager(connection=con)
        # Download data were inputs are needed on a monthly basis.
        finished = False
        for year in range(2019, 2020):
            for month in range(1, 2):
                if year == 2020 and month == 4:
                    finished = True
                    break
                # inputs_manager.DISPATCHINTERCONNECTORRES.add_data(year=year, month=month)
                # inputs_manager.DISPATCHREGIONSUM.add_data(year=year, month=month)
                # inputs_manager.DISPATCHLOAD.add_data(year=year, month=month)
                # inputs_manager.BIDPEROFFER_D.add_data(year=year, month=month)
                # inputs_manager.BIDDAYOFFER_D.add_data(year=year, month=month)
                # inputs_manager.DISPATCHCONSTRAINT.add_data(year=year, month=month)
                # inputs_manager.DISPATCHINTERCONNECTORRES.add_data(year=year, month=month)
                print(month)

            if finished:
                break

        # Download data where inputs are just needed from the latest month.
        # inputs_manager.INTERCONNECTOR.set_data(year=2020, month=3)
        # inputs_manager.LOSSFACTORMODEL.set_data(year=2020, month=3)
        # inputs_manager.LOSSMODEL.set_data(year=2020, month=3)
        # inputs_manager.DUDETAILSUMMARY.set_data(year=2020, month=3)
        # inputs_manager.DUDETAIL.create_table_in_sqlite_db()
        # inputs_manager.DUDETAIL.set_data(year=2020, month=3)
        # inputs_manager.INTERCONNECTORCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.GENCONDATA.set_data(year=2020, month=3)
        # inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.SPDREGIONCONSTRAINT.set_data(year=2020, month=3)
        # inputs_manager.SPDINTERCONNECTORCONSTRAINT.set_data(year=2020, month=3)
        inputs_manager.INTERCONNECTORCONSTRAINT.set_data(year=2020, month=3)  # Interconnector data
        inputs_manager.INTERCONNECTOR.set_data(year=2020, month=3)  # Interconnector data
        inputs_manager.MNSP_INTERCONNECTOR.set_data(year=2020, month=3)

        print('DB Build done.')
        con.close()


def test_historical_interconnector_losses():
    # Create a data base manager.
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        print(interval)
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(INTERCONNECTOR, INTERCONNECTORCONSTRAINT)
        interconnector_loss_coefficients = hi.format_interconnector_loss_coefficients(INTERCONNECTORCONSTRAINT)
        LOSSFACTORMODEL = inputs_manager.LOSSFACTORMODEL.get_data(interval)
        interconnector_demand_coefficients = hi.format_interconnector_loss_demand_coefficient(LOSSFACTORMODEL)
        LOSSMODEL = inputs_manager.LOSSMODEL.get_data(interval)
        interpolation_break_points = hi.format_interpolation_break_points(LOSSMODEL)
        DISPATCHREGIONSUM = inputs_manager.DISPATCHREGIONSUM.get_data(interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)
        inter_flow = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)

        market = markets.Spot()

        inter_flow = inter_flow.loc[:, ['INTERCONNECTORID', 'MWFLOW', 'MWLOSSES']]
        inter_flow.columns = ['interconnector', 'MWFLOW', 'MWLOSSES']
        interconnectors = pd.merge(interconnectors, inter_flow, 'inner', on='interconnector')
        interconnectors['max'] = interconnectors['MWFLOW'] + 0.01
        interconnectors['min'] = interconnectors['MWFLOW'] - 0.01
        interconnectors = interconnectors.loc[:, ['interconnector', 'to_region', 'from_region', 'min', 'max']]
        market.set_interconnectors(interconnectors)

        # Create loss functions on per interconnector basis.
        loss_functions = hi.create_loss_functions(interconnector_loss_coefficients,
                                                  interconnector_demand_coefficients,
                                                  regional_demand.loc[:, ['region', 'loss_function_demand']])

        market.set_interconnector_losses(loss_functions, interpolation_break_points)

        # Calculate dispatch.
        market.dispatch()
        output = market.get_interconnector_flows()

        expected = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        expected = expected.loc[:, ['INTERCONNECTORID', 'MWFLOW', 'MWLOSSES']].sort_values('INTERCONNECTORID')
        expected.columns = ['interconnector', 'flow', 'losses']
        expected = expected.reset_index(drop=True)
        output = output.sort_values('interconnector').reset_index(drop=True)
        comparison = pd.merge(expected, output, 'inner', on='interconnector')
        comparison['diff'] = comparison['losses_x'] - comparison['losses_y']
        comparison['diff'] = comparison['diff'].abs()
        comparison['ok'] = comparison['diff'] < 0.5
        assert (comparison['ok'].all())


def test_using_availability_and_ramp_rates():
    """Test that using the availability and ramp up rate from DISPATCHLOAD always provides an upper bound on ouput.

    Note we only test for units in dispatch mode 0.0, i.e. not fast start units. Fast start units would appear to have
    their max output calculated using another procedure.
    """

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load[dispatch_load['DISPATCHMODE'] == 0.0]
        dispatch_load = dispatch_load.loc[:, ['DUID', 'INITIALMW', 'AVAILABILITY', 'RAMPUPRATE', 'RAMPDOWNRATE',
                                              'TOTALCLEARED', 'DISPATCHMODE']]
        dispatch_load['RAMPMAX'] = dispatch_load['INITIALMW'] + dispatch_load['RAMPUPRATE'] * (5 / 60)
        dispatch_load['RAMPMIN'] = dispatch_load['INITIALMW'] - dispatch_load['RAMPDOWNRATE'] * (5 / 60)
        dispatch_load['assumption'] = ((dispatch_load['RAMPMAX'] + 0.01 >= dispatch_load['TOTALCLEARED']) &
                                       (dispatch_load['AVAILABILITY'] + 0.01 >= dispatch_load['TOTALCLEARED'])) | \
                                      (np.abs(dispatch_load['TOTALCLEARED'] - dispatch_load['RAMPMIN']) < 0.01)
        assert (dispatch_load['assumption'].all())


def test_max_capacity_not_less_than_availability():
    """For historical testing we are using availability as the unit capacity, so we want to test that the unit capacity
       or offer max is never lower than this value."""

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load.loc[:, ['DUID', 'AVAILABILITY']]
        unit_capacity = inputs_manager.DUDETAIL.get_data(interval)
        unit_capacity = pd.merge(unit_capacity, dispatch_load, 'inner', on='DUID')
        unit_capacity['assumption'] = unit_capacity['AVAILABILITY'] <= unit_capacity['MAXCAPACITY']
        assert (unit_capacity['assumption'].all())


def test_determine_unit_limits():
    """Test the procedure for determining unit limits from historical inputs.

    It the limits set should always contain the historical amount dispatched within their bounds.
    """

    # Create a database for the require inputs.
    con = sqlite3.connect('test_files/historical_inputs.db')

    # Create a data base manager.
    inputs_manager = hi.DBManager(connection=con)

    for interval in get_test_intervals():
        dispatch_load = inputs_manager.DISPATCHLOAD.get_data(interval)
        dispatch_load = dispatch_load.loc[:, ['DUID', 'INITIALMW', 'AVAILABILITY', 'TOTALCLEARED', 'SEMIDISPATCHCAP',
                                              'RAMPUPRATE', 'RAMPDOWNRATE', 'DISPATCHMODE']]
        unit_capacity = inputs_manager.BIDPEROFFER_D.get_data(interval)
        unit_capacity = unit_capacity[unit_capacity['BIDTYPE'] == 'ENERGY']
        unit_limits = hi.determine_unit_limits(dispatch_load, unit_capacity)
        unit_limits = pd.merge(unit_limits, dispatch_load.loc[:, ['DUID', 'TOTALCLEARED', 'DISPATCHMODE']], 'inner',
                               left_on='unit', right_on='DUID')
        unit_limits['ramp_max'] = unit_limits['initial_output'] + unit_limits['ramp_up_rate'] * (5 / 60)
        unit_limits['ramp_min'] = unit_limits['initial_output'] - unit_limits['ramp_down_rate'] * (5 / 60)
        # Test the assumption that our calculated limits are not more restrictive then amount historically dispatched.
        unit_limits['assumption'] = ~((unit_limits['TOTALCLEARED'] > unit_limits['capacity'] + 0.01) |
                                      (unit_limits['TOTALCLEARED'] > unit_limits['ramp_max'] + 0.01) |
                                      (unit_limits['TOTALCLEARED'] < unit_limits['ramp_min'] - 0.01))
        assert (unit_limits['assumption'].all())


def test_fcas_trapezium_scaled_availability():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    fails = 0
    passes = 0
    total = 0
    for interval in get_test_intervals():
        DUDETAILSUMMARY = inputs_manager.DUDETAILSUMMARY.get_data(interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = inputs_manager.BIDPEROFFER_D.get_data(interval)
        BIDDAYOFFER_D = inputs_manager.BIDDAYOFFER_D.get_data(interval)

        # Unit dispatch info
        DISPATCHLOAD = inputs_manager.DISPATCHLOAD.get_data(interval)
        unit_limits = hi.determine_unit_limits(DISPATCHLOAD, BIDPEROFFER_D)

        # FCAS bid prepocessing
        BIDPEROFFER_D = hi.scaling_for_agc_enablement_limits(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = hi.scaling_for_agc_ramp_rates(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = hi.scaling_for_uigf(BIDPEROFFER_D, DISPATCHLOAD, DUDETAILSUMMARY)
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.enforce_preconditions_for_enabling_fcas(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD, unit_limits.loc[:, ['unit', 'capacity']])
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.use_historical_actual_availability_to_filter_fcas_bids(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD)

        print('##########  {}'.format(interval))
        for unit in list(DISPATCHLOAD['DUID']):

            if not '{} {}'.format(interval, unit) == '2019/01/30 21:15:00 TORRB1':
                continue

            service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                    'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                    'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min'}

            BIDPEROFFER_D_unit = BIDPEROFFER_D[BIDPEROFFER_D['DUID'] == unit]
            unit_limits_one = unit_limits[unit_limits['unit'] == unit]
            unit_info_one = unit_info[unit_info['unit'] == unit]
            BIDDAYOFFER_D_unit = BIDDAYOFFER_D[BIDDAYOFFER_D['DUID'] == unit]
            DISPATCHLOAD_unit = DISPATCHLOAD[DISPATCHLOAD['DUID'] == unit]

            # Extract just bidding info
            volume_bids = hi.format_volume_bids(BIDPEROFFER_D_unit)
            price_bids = hi.format_price_bids(BIDDAYOFFER_D_unit)
            fcas_trapeziums = hi.format_fcas_trapezium_constraints(BIDPEROFFER_D_unit)

            market = markets.Spot()

            # Add generators to the market.
            market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

            # Set volume of each bids.
            volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info_one['unit']))]
            if volume_bids.empty:
                continue
            market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                            '6', '7', '8', '9', '10']])

            # Set prices of each bid.
            price_bids = price_bids[price_bids['unit'].isin(list(unit_info['unit']))]
            market.set_unit_price_bids(price_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                          '6', '7', '8', '9', '10']])

            # Set unit operating limits.
            if not unit_limits_one.empty:
                market.set_unit_capacity_constraints(unit_limits_one.loc[:, ['unit', 'capacity']])
                market.set_unit_ramp_up_constraints(unit_limits_one.loc[:, ['unit', 'initial_output',
                                                                            'ramp_up_rate']])
                market.set_unit_ramp_down_constraints(unit_limits_one.loc[:, ['unit', 'initial_output',
                                                                              'ramp_down_rate']])

            # Create constraints that enforce the top of the FCAS trapezium.
            if not fcas_trapeziums.empty:
                fcas_availability = fcas_trapeziums.loc[:, ['unit', 'service', 'max_availability']]
                market.set_fcas_max_availability(fcas_availability)
            else:
                continue

            print(unit)
            # Create constraints the enforce the lower and upper slope of the FCAS regulation
            # service trapeziums.
            regulation_trapeziums = fcas_trapeziums[fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
            if not regulation_trapeziums.empty:
                market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)
                market.set_joint_ramping_constraints(regulation_trapeziums.loc[:, ['unit', 'service']],
                                                     unit_limits.loc[:, ['unit', 'initial_output',
                                                                         'ramp_down_rate', 'ramp_up_rate']])

            # Create constraints that enforce the lower and upper slope of the FCAS contingency
            # trapezium. These constrains also scale slopes of the trapezium to ensure the
            # co-dispatch of contingency and regulation services is technically feasible.
            contingency_trapeziums = fcas_trapeziums[~fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
            if not contingency_trapeziums.empty:
                market.set_joint_capacity_constraints(contingency_trapeziums)

            vars = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                    'LOWERREG', 'RAISEREG']

            bounds = DISPATCHLOAD_unit.loc[:, ['DUID'] + vars]
            bounds.columns = ['unit'] + vars

            bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=vars, type_name='service',
                                      value_name='dispatched')

            bounds['service'] = bounds['service'].apply(lambda x: service_name_mapping[x])

            decision_variables = market.decision_variables['bids'].copy()

            decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

            decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

            def last_bids(df):
                return df.iloc[1:]

            decision_variables_remaining_bids = \
                decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

            decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched']
            decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched']
            decision_variables_remaining_bids['lower_bound'] = 0.0
            decision_variables_remaining_bids['upper_bound'] = 0.0

            decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

            market.decision_variables['bids'] = decision_variables

            market.dispatch()

            availabilities = ['RAISE6SECACTUALAVAILABILITY', 'RAISE60SECACTUALAVAILABILITY',
                              'RAISE5MINACTUALAVAILABILITY', 'RAISEREGACTUALAVAILABILITY',
                              'LOWER6SECACTUALAVAILABILITY', 'LOWER60SECACTUALAVAILABILITY',
                              'LOWER5MINACTUALAVAILABILITY', 'LOWERREGACTUALAVAILABILITY']

            availabilities_mapping = {'RAISEREGACTUALAVAILABILITY': 'raise_reg',
                                      'LOWERREGACTUALAVAILABILITY': 'lower_reg',
                                      'RAISE6SECACTUALAVAILABILITY': 'raise_6s',
                                      'RAISE60SECACTUALAVAILABILITY': 'raise_60s',
                                      'RAISE5MINACTUALAVAILABILITY': 'raise_5min',
                                      'LOWER6SECACTUALAVAILABILITY': 'lower_6s',
                                      'LOWER60SECACTUALAVAILABILITY': 'lower_60s',
                                      'LOWER5MINACTUALAVAILABILITY': 'lower_5min'}

            bounds = DISPATCHLOAD_unit.loc[:, ['DUID'] + availabilities]
            bounds.columns = ['unit'] + availabilities

            availabilities = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=availabilities,
                                              type_name='service', value_name='availability')

            availabilities['service'] = availabilities['service'].apply(lambda x: availabilities_mapping[x])

            output = market.get_fcas_availability()
            output.columns = ['unit', 'service', 'availability_measured']

            availabilities = pd.merge(availabilities, output, 'left', on=['unit', 'service'])

            availabilities['availability_measured'] = availabilities['availability_measured'].fillna(0)

            availabilities['error'] = availabilities['availability_measured'] - availabilities['availability']

            availabilities['match'] = availabilities['error'].abs() < 0.1


            fails += len(availabilities['match']) - availabilities['match'].sum()
            passes += availabilities['match'].sum()
            total += len(availabilities['match'])

        print('fails {}'.format(fails))
        print('passes {}'.format(passes))
        print('total {}'.format(passes))


def test_slack_in_generic_constraints():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        DUDETAILSUMMARY = inputs_manager.DUDETAILSUMMARY.get_data(interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = inputs_manager.BIDPEROFFER_D.get_data(interval)

        # Unit dispatch info
        DISPATCHLOAD = inputs_manager.DISPATCHLOAD.get_data(interval)

        # Interconnector definitions
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(INTERCONNECTOR,
                                                               INTERCONNECTORCONSTRAINT)

        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        # Get constraint data
        DISPATCHCONSTRAINT = inputs_manager.DISPATCHCONSTRAINT.get_data(interval)
        GENCONDATA = inputs_manager.GENCONDATA.get_data(interval)
        SPDINTERCONNECTORCONSTRAINT = inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(interval)
        SPDREGIONCONSTRAINT = inputs_manager.SPDREGIONCONSTRAINT.get_data(interval)
        SPDCONNECTIONPOINTCONSTRAINT = inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(interval)

        service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                'ENERGY': 'energy'}

        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)
        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)

        print('##########  {}'.format(interval))

        # Extract just bidding info
        volume_bids = hi.format_volume_bids(BIDPEROFFER_D)

        market = markets.Spot()

        # Add generators to the market.
        market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        if volume_bids.empty:
            continue
        market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                        '6', '7', '8', '9', '10']])

        market.set_interconnectors(interconnectors)
        market.set_generic_constraints(generic_rhs)
        market.make_constraints_elastic('generic', violation_cost=0.0)
        market.link_units_to_generic_constraints(unit_generic_lhs)
        market.link_regions_to_generic_constraints(region_generic_lhs)
        market.link_interconnectors_to_generic_constraints(interconnector_generic_lhs)

        vars = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                'LOWERREG', 'RAISEREG']

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + vars]
        bounds.columns = ['unit'] + vars

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=vars, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: service_name_mapping[x])

        decision_variables = market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        market.decision_variables['bids'] = decision_variables

        flow_variables = market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on='interconnector')
        flow_variables['lower_bound'] = flow_variables['flow']
        flow_variables['upper_bound'] = flow_variables['flow']
        flow_variables = flow_variables.drop(['flow'], axis=1)
        market.decision_variables['interconnectors'] = flow_variables

        market.dispatch()

        def calc_slack(rhs, lhs, type):
            if type == '<=':
                slack = rhs - lhs
            elif type == '>=':
                slack = lhs - rhs
            else:
                slack = 0.0
            if slack < 0.0:
                slack = 0.0
            return slack

        generic_cons_slack = market.constraints_rhs_and_type['generic']
        generic_cons_slack = pd.merge(generic_cons_slack, DISPATCHCONSTRAINT, left_on='set', right_on='CONSTRAINTID')
        generic_cons_slack['aemo_slack'] = (generic_cons_slack['RHS'] - generic_cons_slack['LHS'])
        generic_cons_slack['aemo_slack'] = \
            generic_cons_slack.apply(lambda x: calc_slack(x['RHS'], x['LHS'], x['type']), axis=1)
        generic_cons_slack['comp'] = (generic_cons_slack['aemo_slack'] - generic_cons_slack['slack']).abs()
        generic_cons_slack['no_error'] = generic_cons_slack['comp'] < 0.05
        assert generic_cons_slack['no_error'].all()
    con.close()


def test_slack_in_generic_constraints_use_fcas_requirments_interface():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        DUDETAILSUMMARY = inputs_manager.DUDETAILSUMMARY.get_data(interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = inputs_manager.BIDPEROFFER_D.get_data(interval)

        # Unit dispatch info
        DISPATCHLOAD = inputs_manager.DISPATCHLOAD.get_data(interval)

        # Interconnector definitions
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(INTERCONNECTOR,
                                                               INTERCONNECTORCONSTRAINT)

        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        # Get constraint data
        DISPATCHCONSTRAINT = inputs_manager.DISPATCHCONSTRAINT.get_data(interval)
        GENCONDATA = inputs_manager.GENCONDATA.get_data(interval)
        SPDINTERCONNECTORCONSTRAINT = inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(interval)
        SPDREGIONCONSTRAINT = inputs_manager.SPDREGIONCONSTRAINT.get_data(interval)
        SPDCONNECTIONPOINTCONSTRAINT = inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(interval)

        service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                'ENERGY': 'energy'}

        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)
        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)

        print('##########  {}'.format(interval))

        # Extract just bidding info
        volume_bids = hi.format_volume_bids(BIDPEROFFER_D)

        market = markets.Spot()

        # Add generators to the market.
        market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        if volume_bids.empty:
            continue
        market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                        '6', '7', '8', '9', '10']])

        # FCAS volumes required.
        fcas_requirements = hi.format_fcas_market_requirements(
            SPDREGIONCONSTRAINT, DISPATCHCONSTRAINT, GENCONDATA)
        # Set FCAS requirements.
        market.set_fcas_requirements_constraints(fcas_requirements)
        market.make_constraints_elastic('fcas', violation_cost=0.0)

        generic_rhs = generic_rhs[~generic_rhs['set'].isin(list(fcas_requirements['set']))]
        region_generic_lhs = region_generic_lhs[~region_generic_lhs['set'].isin(list(fcas_requirements['set']))]
        market.set_interconnectors(interconnectors)
        market.set_generic_constraints(generic_rhs)
        market.make_constraints_elastic('generic', violation_cost=0.0)
        market.link_units_to_generic_constraints(unit_generic_lhs)
        market.link_interconnectors_to_generic_constraints(interconnector_generic_lhs)
        market.link_regions_to_generic_constraints(region_generic_lhs)

        vars = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                'LOWERREG', 'RAISEREG']

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + vars]
        bounds.columns = ['unit'] + vars

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=vars, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: service_name_mapping[x])

        decision_variables = market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        market.decision_variables['bids'] = decision_variables

        flow_variables = market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on='interconnector')
        flow_variables['lower_bound'] = flow_variables['flow']
        flow_variables['upper_bound'] = flow_variables['flow']
        flow_variables = flow_variables.drop(['flow'], axis=1)
        market.decision_variables['interconnectors'] = flow_variables

        market.dispatch()

        def calc_slack(rhs, lhs, type):
            if type == '<=':
                slack = rhs - lhs
            elif type == '>=':
                slack = lhs - rhs
            else:
                slack = 0.0
            if slack < 0.0:
                slack = 0.0
            return slack

        generic_cons_slack = market.constraints_rhs_and_type['generic']
        generic_cons_slack = pd.merge(generic_cons_slack, DISPATCHCONSTRAINT, left_on='set', right_on='CONSTRAINTID')
        generic_cons_slack['aemo_slack'] = (generic_cons_slack['RHS'] - generic_cons_slack['LHS'])
        generic_cons_slack['aemo_slack'] = \
            generic_cons_slack.apply(lambda x: calc_slack(x['RHS'], x['LHS'], x['type']), axis=1)
        generic_cons_slack['comp'] = (generic_cons_slack['aemo_slack'] - generic_cons_slack['slack']).abs()
        generic_cons_slack['no_error'] = generic_cons_slack['comp'] < 0.05
        assert generic_cons_slack['no_error'].all()
    con.close()


def test_slack_in_generic_constraints_with_all_features():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        # Transform the historical input data into the format accepted
        # by the Spot market class.

        # Unit info.
        DUDETAILSUMMARY = inputs_manager.DUDETAILSUMMARY.get_data(interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = inputs_manager.BIDPEROFFER_D.get_data(interval)
        BIDDAYOFFER_D = inputs_manager.BIDDAYOFFER_D.get_data(interval)

        # The unit operating conditions at the start of the historical interval.
        DISPATCHLOAD = inputs_manager.DISPATCHLOAD.get_data(interval)
        DISPATCHLOAD['AGCSTATUS'] = pd.to_numeric(DISPATCHLOAD['AGCSTATUS'])
        unit_limits = hi.determine_unit_limits(DISPATCHLOAD, BIDPEROFFER_D)

        # FCAS bid prepocessing
        BIDPEROFFER_D = \
            hi.scaling_for_agc_enablement_limits(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = \
            hi.scaling_for_agc_ramp_rates(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = \
            hi.scaling_for_uigf(BIDPEROFFER_D, DISPATCHLOAD, DUDETAILSUMMARY)
        BIDPEROFFER_D, BIDDAYOFFER_D = \
            hi.enforce_preconditions_for_enabling_fcas(
                BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD, unit_limits.loc[:, ['unit', 'capacity']])
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.use_historical_actual_availability_to_filter_fcas_bids(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD)

        # Change bidding data to conform to nempy input format.
        volume_bids = hi.format_volume_bids(BIDPEROFFER_D)
        price_bids = hi.format_price_bids(BIDDAYOFFER_D)
        fcas_trapeziums = hi.format_fcas_trapezium_constraints(BIDPEROFFER_D)

        # Demand on regional basis.
        DISPATCHREGIONSUM = inputs_manager.DISPATCHREGIONSUM.get_data(interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)

        # FCAS volumes required.
        SPDREGIONCONSTRAINT = inputs_manager.SPDREGIONCONSTRAINT.get_data(interval)
        DISPATCHCONSTRAINT = inputs_manager.DISPATCHCONSTRAINT.get_data(interval)
        GENCONDATA = inputs_manager.GENCONDATA.get_data(interval)
        fcas_requirements = hi.format_fcas_market_requirements(
            SPDREGIONCONSTRAINT, DISPATCHCONSTRAINT, GENCONDATA)

        # Generic constraint definitions.
        SPDINTERCONNECTORCONSTRAINT = inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(interval)
        SPDCONNECTIONPOINTCONSTRAINT = inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(interval)
        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)

        # Interconnector details.
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(
            INTERCONNECTOR, INTERCONNECTORCONSTRAINT)
        interconnector_loss_coefficients = hi.format_interconnector_loss_coefficients(INTERCONNECTORCONSTRAINT)
        LOSSFACTORMODEL = inputs_manager.LOSSFACTORMODEL.get_data(interval)
        interconnector_demand_coefficients = hi.format_interconnector_loss_demand_coefficient(LOSSFACTORMODEL)
        LOSSMODEL = inputs_manager.LOSSMODEL.get_data(interval)
        interpolation_break_points = hi.format_interpolation_break_points(LOSSMODEL)
        loss_functions = hi.create_loss_functions(interconnector_loss_coefficients, interconnector_demand_coefficients,
                                                  regional_demand.loc[:, ['region', 'loss_function_demand']])

        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        # Create a market instance.
        market = markets.Spot()

        # Add generators to the market.
        market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                        '6', '7', '8', '9', '10']])

        # Set prices of each bid.
        price_bids = price_bids[price_bids['unit'].isin(list(unit_info['unit']))]
        market.set_unit_price_bids(price_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                      '6', '7', '8', '9', '10']])

        # Set unit operating limits.
        market.set_unit_capacity_constraints(unit_limits.loc[:, ['unit', 'capacity']])
        market.set_unit_ramp_up_constraints(unit_limits.loc[:, ['unit', 'initial_output', 'ramp_up_rate']])
        market.set_unit_ramp_down_constraints(unit_limits.loc[:, ['unit', 'initial_output', 'ramp_down_rate']])

        # Create constraints that enforce the top of the FCAS trapezium.
        fcas_availability = fcas_trapeziums.loc[:, ['unit', 'service', 'max_availability']]
        market.set_fcas_max_availability(fcas_availability)

        # Create constraints the enforce the lower and upper slope of the FCAS regulation
        # service trapeziums.
        regulation_trapeziums = fcas_trapeziums[fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)
        market.make_constraints_elastic('energy_and_regulation_capacity', 14000.0)
        market.set_joint_ramping_constraints(regulation_trapeziums.loc[:, ['unit', 'service']],
                                             unit_limits.loc[:, ['unit', 'initial_output',
                                                                 'ramp_down_rate', 'ramp_up_rate']])
        market.make_constraints_elastic('joint_ramping', 14000.0)

        # Create constraints that enforce the lower and upper slope of the FCAS contingency
        # trapezium. These constrains also scale slopes of the trapezium to ensure the
        # co-dispatch of contingency and regulation services is technically feasible.
        contingency_trapeziums = fcas_trapeziums[~fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        market.set_joint_capacity_constraints(contingency_trapeziums)
        market.make_constraints_elastic('joint_capacity', 14000.0)

        # Set regional demand.
        market.set_demand_constraints(regional_demand.loc[:, ['region', 'demand']])

        # Set FCAS requirements.
        # market.set_fcas_requirements_constraints(fcas_requirements)

        # Set generic constraints
        # generic_rhs = generic_rhs[~generic_rhs['set'].isin(list(fcas_requirements['set']))]
        # region_generic_lhs = region_generic_lhs[~region_generic_lhs['set'].isin(list(fcas_requirements['set']))]
        market.set_generic_constraints(generic_rhs)
        GENCONDATA['cost'] = GENCONDATA['GENERICCONSTRAINTWEIGHT'] * 14000.0
        generic_constraint_violation_costs = GENCONDATA.loc[:, ['GENCONID', 'cost']]
        generic_constraint_violation_costs.columns = ['set', 'cost']
        market.make_constraints_elastic('generic', generic_constraint_violation_costs)
        market.link_units_to_generic_constraints(unit_generic_lhs)
        market.link_interconnectors_to_generic_constraints(interconnector_generic_lhs)
        market.link_regions_to_generic_constraints(region_generic_lhs)

        # Create the interconnectors.
        market.set_interconnectors(interconnectors)

        # Create loss functions on per interconnector basis.
        market.set_interconnector_losses(loss_functions, interpolation_break_points)

        vars = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                'LOWERREG', 'RAISEREG']

        service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                'ENERGY': 'energy'}

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + vars]
        bounds.columns = ['unit'] + vars

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=vars, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: service_name_mapping[x])

        decision_variables = market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        market.decision_variables['bids'] = decision_variables

        flow_variables = market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on='interconnector')
        flow_variables['lower_bound'] = flow_variables['flow']
        flow_variables['upper_bound'] = flow_variables['flow']
        flow_variables = flow_variables.drop(['flow'], axis=1)
        market.decision_variables['interconnectors'] = flow_variables

        market.dispatch()

        def calc_slack(rhs, lhs, type):
            if type == '<=':
                slack = rhs - lhs
            elif type == '>=':
                slack = lhs - rhs
            else:
                slack = 0.0
            if slack < 0.0:
                slack = 0.0
            return slack

        generic_cons_slack = market.constraints_rhs_and_type['generic']
        generic_cons_slack = pd.merge(generic_cons_slack, DISPATCHCONSTRAINT, left_on='set', right_on='CONSTRAINTID')
        generic_cons_slack['aemo_slack'] = (generic_cons_slack['RHS'] - generic_cons_slack['LHS'])
        generic_cons_slack['aemo_slack'] = \
            generic_cons_slack.apply(lambda x: calc_slack(x['RHS'], x['LHS'], x['type']), axis=1)
        generic_cons_slack['comp'] = (generic_cons_slack['aemo_slack'] - generic_cons_slack['slack']).abs()
        generic_cons_slack['no_error'] = generic_cons_slack['comp'] < 0.05
        assert generic_cons_slack['no_error'].all()
    con.close()


def test_hist_dispatch_values_feasible_without_generic_constraints():
    con = sqlite3.connect('test_files/historical_inputs.db')
    inputs_manager = hi.DBManager(connection=con)
    for interval in get_test_intervals():
        # Transform the historical input data into the format accepted
        # by the Spot market class.

        # Unit info.
        DUDETAILSUMMARY = inputs_manager.DUDETAILSUMMARY.get_data(interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = inputs_manager.BIDPEROFFER_D.get_data(interval)
        BIDDAYOFFER_D = inputs_manager.BIDDAYOFFER_D.get_data(interval)

        # The unit operating conditions at the start of the historical interval.
        DISPATCHLOAD = inputs_manager.DISPATCHLOAD.get_data(interval)
        DISPATCHLOAD['AGCSTATUS'] = pd.to_numeric(DISPATCHLOAD['AGCSTATUS'])
        unit_limits = hi.determine_unit_limits(DISPATCHLOAD, BIDPEROFFER_D)

        # FCAS bid prepocessing
        BIDPEROFFER_D = \
            hi.scaling_for_agc_enablement_limits(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = \
            hi.scaling_for_agc_ramp_rates(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = \
            hi.scaling_for_uigf(BIDPEROFFER_D, DISPATCHLOAD, DUDETAILSUMMARY)
        BIDPEROFFER_D, BIDDAYOFFER_D = \
            hi.enforce_preconditions_for_enabling_fcas(
                BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD, unit_limits.loc[:, ['unit', 'capacity']])
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.use_historical_actual_availability_to_filter_fcas_bids(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD)

        # Change bidding data to conform to nempy input format.
        volume_bids = hi.format_volume_bids(BIDPEROFFER_D)
        price_bids = hi.format_price_bids(BIDDAYOFFER_D)
        fcas_trapeziums = hi.format_fcas_trapezium_constraints(BIDPEROFFER_D)

        # Demand on regional basis.
        DISPATCHREGIONSUM = inputs_manager.DISPATCHREGIONSUM.get_data(interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)

        # FCAS volumes required.
        SPDREGIONCONSTRAINT = inputs_manager.SPDREGIONCONSTRAINT.get_data(interval)
        DISPATCHCONSTRAINT = inputs_manager.DISPATCHCONSTRAINT.get_data(interval)
        GENCONDATA = inputs_manager.GENCONDATA.get_data(interval)
        fcas_requirements = hi.format_fcas_market_requirements(
            SPDREGIONCONSTRAINT, DISPATCHCONSTRAINT, GENCONDATA)

        # Generic constraint definitions.
        SPDINTERCONNECTORCONSTRAINT = inputs_manager.SPDINTERCONNECTORCONSTRAINT.get_data(interval)
        SPDCONNECTIONPOINTCONSTRAINT = inputs_manager.SPDCONNECTIONPOINTCONSTRAINT.get_data(interval)
        generic_rhs = hi.format_generic_constraints_rhs_and_type(DISPATCHCONSTRAINT, GENCONDATA)
        unit_generic_lhs = hi.format_generic_unit_lhs(SPDCONNECTIONPOINTCONSTRAINT, DUDETAILSUMMARY)
        interconnector_generic_lhs = hi.format_generic_interconnector_lhs(SPDINTERCONNECTORCONSTRAINT)
        region_generic_lhs = hi.format_generic_region_lhs(SPDREGIONCONSTRAINT)

        # Interconnector details.
        INTERCONNECTOR = inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = inputs_manager.INTERCONNECTORCONSTRAINT.get_data(interval)
        interconnectors = hi.format_interconnector_definitions(
            INTERCONNECTOR, INTERCONNECTORCONSTRAINT)
        interconnector_loss_coefficients = hi.format_interconnector_loss_coefficients(INTERCONNECTORCONSTRAINT)
        LOSSFACTORMODEL = inputs_manager.LOSSFACTORMODEL.get_data(interval)
        interconnector_demand_coefficients = hi.format_interconnector_loss_demand_coefficient(LOSSFACTORMODEL)
        LOSSMODEL = inputs_manager.LOSSMODEL.get_data(interval)
        interpolation_break_points = hi.format_interpolation_break_points(LOSSMODEL)
        loss_functions = hi.create_loss_functions(interconnector_loss_coefficients, interconnector_demand_coefficients,
                                                  regional_demand.loc[:, ['region', 'loss_function_demand']])

        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = inputs_manager.DISPATCHINTERCONNECTORRES.get_data(interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        # Create a market instance.
        market = markets.Spot()

        # Add generators to the market.
        market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                        '6', '7', '8', '9', '10']])

        # Set prices of each bid.
        price_bids = price_bids[price_bids['unit'].isin(list(unit_info['unit']))]
        market.set_unit_price_bids(price_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                      '6', '7', '8', '9', '10']])

        # Set unit operating limits.
        market.set_unit_capacity_constraints(unit_limits.loc[:, ['unit', 'capacity']])
        market.set_unit_ramp_up_constraints(unit_limits.loc[:, ['unit', 'initial_output', 'ramp_up_rate']])
        market.set_unit_ramp_down_constraints(unit_limits.loc[:, ['unit', 'initial_output', 'ramp_down_rate']])

        # Create constraints that enforce the top of the FCAS trapezium.
        fcas_availability = fcas_trapeziums.loc[:, ['unit', 'service', 'max_availability']]
        market.set_fcas_max_availability(fcas_availability)

        # Create constraints the enforce the lower and upper slope of the FCAS regulation
        # service trapeziums.
        regulation_trapeziums = fcas_trapeziums[fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        market.set_energy_and_regulation_capacity_constraints(regulation_trapeziums)
        market.make_constraints_elastic('energy_and_regulation_capacity', 14000.0)
        market.set_joint_ramping_constraints(regulation_trapeziums.loc[:, ['unit', 'service']],
                                             unit_limits.loc[:, ['unit', 'initial_output',
                                                                 'ramp_down_rate', 'ramp_up_rate']])
        market.make_constraints_elastic('joint_ramping', 14000.0)

        # Create constraints that enforce the lower and upper slope of the FCAS contingency
        # trapezium. These constrains also scale slopes of the trapezium to ensure the
        # co-dispatch of contingency and regulation services is technically feasible.
        contingency_trapeziums = fcas_trapeziums[~fcas_trapeziums['service'].isin(['raise_reg', 'lower_reg'])]
        market.set_joint_capacity_constraints(contingency_trapeziums)
        market.make_constraints_elastic('joint_capacity', 14000.0)

        # Set regional demand.
        market.set_demand_constraints(regional_demand.loc[:, ['region', 'demand']])

        # Create the interconnectors.
        market.set_interconnectors(interconnectors)

        # Create loss functions on per interconnector basis.
        market.set_interconnector_losses(loss_functions, interpolation_break_points)

        vars = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                'LOWERREG', 'RAISEREG']

        service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                'ENERGY': 'energy'}

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + vars]
        bounds.columns = ['unit'] + vars

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=vars, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: service_name_mapping[x])

        decision_variables = market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched']
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        market.decision_variables['bids'] = decision_variables

        flow_variables = market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on='interconnector')
        flow_variables['lower_bound'] = flow_variables['flow']
        flow_variables['upper_bound'] = flow_variables['flow']
        flow_variables = flow_variables.drop(['flow'], axis=1)
        market.decision_variables['interconnectors'] = flow_variables

        market.dispatch()
    con.close()


def test_hist_dispatch_values_meet_demand_constraints():
    inputs_database = 'test_files/historical_inputs.db'
    for interval in get_test_intervals():
        market = HistoricalSpotMarket(inputs_database=inputs_database, interval=interval)
        market.add_unit_bids_to_market()
        market.add_interconnectors_to_market()
        market.set_unit_dispatch_to_historical_values()
        market.set_interconnector_flow_to_historical_values()
        market.dispatch()


        # inter_flows = market.get_interconnector_flows()
        #
        # bass_link_flow = inter_flows[inter_flows['interconnector']=='T-V-MNSP1']['flow'].iloc[0]
        #
        # if bass_link_flow > 0.0:
        #     loss_functions['from_region_loss_share'] = np.where(loss_functions['interconnector']=='T-V-MNSP1', 1.0,
        #                                                         loss_functions['from_region_loss_share'])
        #     market.set_interconnector_losses(loss_functions, interpolation_break_points)
        #     market.dispatch()

        test_passed = market.is_regional_demand_meet()
        market.con.close()
        assert test_passed


class HistoricalSpotMarket:
    def __init__(self, inputs_database, interval):
        self.con = sqlite3.connect(inputs_database)
        self.inputs_manager = hi.DBManager(connection=self.con)
        self.interval = interval
        self.services = ['TOTALCLEARED', 'LOWER5MIN', 'LOWER60SEC', 'LOWER6SEC', 'RAISE5MIN', 'RAISE60SEC', 'RAISE6SEC',
                        'LOWERREG', 'RAISEREG']
        self.service_name_mapping = {'TOTALCLEARED': 'energy', 'RAISEREG': 'raise_reg', 'LOWERREG': 'lower_reg',
                                     'RAISE6SEC': 'raise_6s', 'RAISE60SEC': 'raise_60s', 'RAISE5MIN': 'raise_5min',
                                     'LOWER6SEC': 'lower_6s', 'LOWER60SEC': 'lower_60s', 'LOWER5MIN': 'lower_5min',
                                     'ENERGY': 'energy'}
        self.market = markets.Spot()

    def add_unit_bids_to_market(self):
        # Unit info.
        DUDETAILSUMMARY = self.inputs_manager.DUDETAILSUMMARY.get_data(self.interval)
        unit_info = hi.format_unit_info(DUDETAILSUMMARY)

        # Unit bids.
        BIDPEROFFER_D = self.inputs_manager.BIDPEROFFER_D.get_data(self.interval)
        BIDDAYOFFER_D = self.inputs_manager.BIDDAYOFFER_D.get_data(self.interval)

        # The unit operating conditions at the start of the historical interval.
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)
        DISPATCHLOAD['AGCSTATUS'] = pd.to_numeric(DISPATCHLOAD['AGCSTATUS'])
        unit_limits = hi.determine_unit_limits(DISPATCHLOAD, BIDPEROFFER_D)

        # FCAS bid prepocessing
        BIDPEROFFER_D = hi.scaling_for_agc_enablement_limits(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = hi.scaling_for_agc_ramp_rates(BIDPEROFFER_D, DISPATCHLOAD)
        BIDPEROFFER_D = hi.scaling_for_uigf(BIDPEROFFER_D, DISPATCHLOAD, DUDETAILSUMMARY)
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.enforce_preconditions_for_enabling_fcas(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD, unit_limits.loc[:, ['unit', 'capacity']])
        BIDPEROFFER_D, BIDDAYOFFER_D = hi.use_historical_actual_availability_to_filter_fcas_bids(
            BIDPEROFFER_D, BIDDAYOFFER_D, DISPATCHLOAD)

        # Change bidding data to conform to nempy input format.
        volume_bids = hi.format_volume_bids(BIDPEROFFER_D)
        price_bids = hi.format_price_bids(BIDDAYOFFER_D)

        # Add generators to the market.
        self.market.set_unit_info(unit_info.loc[:, ['unit', 'region', 'dispatch_type']])

        # Set volume of each bids.
        volume_bids = volume_bids[volume_bids['unit'].isin(list(unit_info['unit']))]
        self.market.set_unit_volume_bids(volume_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                        '6', '7', '8', '9', '10']])

        # Set prices of each bid.
        price_bids = price_bids[price_bids['unit'].isin(list(unit_info['unit']))]
        self.market.set_unit_price_bids(price_bids.loc[:, ['unit', 'service', '1', '2', '3', '4', '5',
                                                      '6', '7', '8', '9', '10']])

    def add_interconnectors_to_market(self):
        # Demand on regional basis.
        DISPATCHREGIONSUM = self.inputs_manager.DISPATCHREGIONSUM.get_data(self.interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)

        # Interconnector details.
        INTERCONNECTOR = self.inputs_manager.INTERCONNECTOR.get_data()
        INTERCONNECTORCONSTRAINT = self.inputs_manager.INTERCONNECTORCONSTRAINT.get_data(self.interval)
        interconnectors = hi.format_interconnector_definitions(INTERCONNECTOR, INTERCONNECTORCONSTRAINT)
        MNSP_INTERCONNECTOR = self.inputs_manager.MNSP_INTERCONNECTOR.get_data(self.interval)
        mnsp_transmission_loss_factors = hi.format_mnsp_transmission_loss_factors(MNSP_INTERCONNECTOR,
                                                                                  INTERCONNECTORCONSTRAINT,
                                                                                  INTERCONNECTOR)
        interconnectors = hi.add_inerconnector_transmission_loss_factors(interconnectors,
                                                                         mnsp_transmission_loss_factors)

        bass_link, interconnectors = self._split_out_bass_link(interconnectors)
        bass_link = hi.split_interconnectors_definitions_into_two_one_directional_links(bass_link)
        interconnectors = pd.concat([interconnectors, bass_link])

        interconnector_loss_coefficients = hi.format_interconnector_loss_coefficients(INTERCONNECTORCONSTRAINT)
        LOSSFACTORMODEL = self.inputs_manager.LOSSFACTORMODEL.get_data(self.interval)
        interconnector_demand_coefficients = hi.format_interconnector_loss_demand_coefficient(LOSSFACTORMODEL)
        LOSSMODEL = self.inputs_manager.LOSSMODEL.get_data(self.interval)
        interpolation_break_points = hi.format_interpolation_break_points(LOSSMODEL)
        loss_functions = hi.create_loss_functions(interconnector_loss_coefficients,
                                                  interconnector_demand_coefficients,
                                                  regional_demand.loc[:, ['region', 'loss_function_demand']])

        bass_link, loss_functions = self._split_out_bass_link(loss_functions)
        bass_link = hi.split_interconnector_loss_functions_into_two_directional_links(bass_link)
        loss_functions = pd.concat([loss_functions, bass_link])

        bass_link, interpolation_break_points = self._split_out_bass_link(interpolation_break_points)
        bass_link = hi.split_interconnector_interpolation_break_points_into_two_directional_links(bass_link)
        interpolation_break_points = pd.concat([interpolation_break_points, bass_link])

        # Create the interconnectors.
        self.market.set_interconnectors(interconnectors)

        # Create loss functions on per interconnector basis.
        self.market.set_interconnector_losses(loss_functions, interpolation_break_points)

    @staticmethod
    def _split_out_bass_link(interconnectors):
        bass_link = interconnectors[interconnectors['interconnector']=='T-V-MNSP1']
        interconnectors = interconnectors[interconnectors['interconnector'] != 'T-V-MNSP1']
        return bass_link, interconnectors

    def set_unit_dispatch_to_historical_values(self):
        DISPATCHLOAD = self.inputs_manager.DISPATCHLOAD.get_data(self.interval)

        bounds = DISPATCHLOAD.loc[:, ['DUID'] + self.services]
        bounds.columns = ['unit'] + self.services

        bounds = hf.stack_columns(bounds, cols_to_keep=['unit'], cols_to_stack=self.services, type_name='service',
                                  value_name='dispatched')

        bounds['service'] = bounds['service'].apply(lambda x: self.service_name_mapping[x])

        decision_variables = self.market.decision_variables['bids'].copy()

        decision_variables = pd.merge(decision_variables, bounds, on=['unit', 'service'])

        decision_variables_first_bid = decision_variables.groupby(['unit', 'service'], as_index=False).first()

        def last_bids(df):
            return df.iloc[1:]

        decision_variables_remaining_bids = \
            decision_variables.groupby(['unit', 'service'], as_index=False).apply(last_bids)

        decision_variables_first_bid['lower_bound'] = decision_variables_first_bid['dispatched'] - 0.001
        decision_variables_first_bid['upper_bound'] = decision_variables_first_bid['dispatched'] + 0.001
        decision_variables_remaining_bids['lower_bound'] = 0.0
        decision_variables_remaining_bids['upper_bound'] = 0.0

        decision_variables = pd.concat([decision_variables_first_bid, decision_variables_remaining_bids])

        self.market.decision_variables['bids'] = decision_variables

    def set_interconnector_flow_to_historical_values(self):
        # Historical interconnector dispatch
        DISPATCHINTERCONNECTORRES = self.inputs_manager.DISPATCHINTERCONNECTORRES.get_data(self.interval)
        interconnector_flow = DISPATCHINTERCONNECTORRES.loc[:, ['INTERCONNECTORID', 'MWFLOW']]
        interconnector_flow.columns = ['interconnector', 'flow']

        bass_link, loss_functions = self._split_out_bass_link(interconnector_flow)
        bass_link = hi.split_interconnector_flow_into_two_directional_links(bass_link)
        interconnector_flow = pd.concat([interconnector_flow, bass_link])

        flow_variables = self.market.decision_variables['interconnectors']
        flow_variables = pd.merge(flow_variables, interconnector_flow, 'inner', on='interconnector')
        flow_variables['lower_bound'] = flow_variables['flow'] - 0.1
        flow_variables['upper_bound'] = flow_variables['flow'] + 0.1
        flow_variables = flow_variables.drop(['flow'], axis=1)

        self.market.decision_variables['interconnectors'] = flow_variables

    def dispatch(self):
        self.market.dispatch()

    def is_regional_demand_meet(self, tolerance=0.5):
        DISPATCHREGIONSUM = self.inputs_manager.DISPATCHREGIONSUM.get_data(self.interval)
        regional_demand = hi.format_regional_demand(DISPATCHREGIONSUM)
        region_summary = self.market.get_region_dispatch_summary()
        region_summary = pd.merge(region_summary, regional_demand, on='region')
        region_summary['calc_demand'] = region_summary['dispatch'] + region_summary['inflow'] \
                                        - region_summary['interconnector_losses'] - \
                                        region_summary['transmission_losses']
        region_summary['diff'] =region_summary['calc_demand'] - region_summary['demand']
        region_summary['no_error'] = region_summary['diff'].abs() < tolerance
        return region_summary['no_error'].all()





