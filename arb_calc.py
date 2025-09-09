import pandas as pd
import numpy as np
import asyncio
import cutgems_utils.get as get
from cutgems_utils.get.providers import polymarket_v2 as polymarket
from cutgems_utils.get.providers import kambi
from sportsbooks_info import(
    SPORTSBOOKS_URL
)

USDSEK = get.usdsek()

async def get_sportsbooks_prices(
        sport:str='nba',
        exclude_live:bool=True,
    ):
    
    # unpack
    polymarket_result, betmgm_prices = await asyncio.gather( # , betinia_prices
        polymarket.get_polymarket_prices_async(
            sport=sport,
            include_spread=False,
            include_total=False,
            include_moneyline=True,
            include_avalible_volume=True,
        ),
        kambi.get_betmgm_prices_async(sport=sport)
    )
    polymarket_prices, polymarket_volume = polymarket_result

    # Process Prices
    prices = polymarket_prices[[
        'start_date',
        'swe_time',
        'state',
        'home_team',
        'visitor_team',
        'home_short',
        'visitor_short',
        'moneyline_home_price',
        'moneyline_visitor_price'
    ]].rename(
        columns={
            'moneyline_home_price': 'polymarket_moneyline_home_price',
            'moneyline_visitor_price': 'polymarket_moneyline_visitor_price'
        }
    ).merge(
        betmgm_prices[[
            'moneyline_home_price',
            'moneyline_visitor_price'
        ]].rename(
            columns={
                'moneyline_home_price': 'betmgm_moneyline_home_price',
                'moneyline_visitor_price': 'betmgm_moneyline_visitor_price'
            }
        ),
        right_index=True,
        left_index=True,
        how='outer'
    )
    # .merge(
    #     betinia_prices[[
    #         'moneyline_home_price',
    #         'moneyline_visitor_price'
    #     ]].rename(
    #         columns={
    #             'moneyline_home_price': 'betinia_moneyline_home_price',
    #             'moneyline_visitor_price': 'betinia_moneyline_visitor_price'
    #         }
    #     ),
    #     right_index=True,
    #     left_index=True,
    #     how='outer',
    # ).sort_values(by='swe_time')

    # Only keep rows that have prices from polymarket and at least one other provider
    prices['provider_count'] = (
        (~prices[['betmgm_moneyline_home_price', 'betmgm_moneyline_visitor_price']].isna()).any(axis=1).astype(int)
        # + (~prices[['betinia_moneyline_home_price', 'betinia_moneyline_visitor_price']].isna()).any(axis=1).astype(int)
    )
    prices = prices[prices['provider_count'] >= 1].drop(columns='provider_count').dropna(subset=['polymarket_moneyline_home_price','polymarket_moneyline_visitor_price'])

    prices = prices.dropna(subset=[
        'polymarket_moneyline_home_price',
        'polymarket_moneyline_visitor_price'
    ])

    if exclude_live:
        prices = prices.loc[prices.state == 'NOT_STARTED']

    # Process Volume
    volume = polymarket_volume[['moneyline_home_volume', 'moneyline_visitor_volume']].rename(
        columns={
            'moneyline_home_volume': 'polymarket_home_volume',
            'moneyline_visitor_volume': 'polymarket_visitor_volume'
        }
    )
    # betinia_volume = pd.DataFrame(
    #     np.full((len(volume.index), 2), 1e6, dtype=float),
    #     index=volume.index,
    #     columns=['betinia_home_volume', 'betinia_visitor_volume']
    # )
    betmgm_volume = pd.DataFrame(
        np.full((len(volume.index), 2), 1e6, dtype=float),
        index=volume.index,
        columns=['betmgm_home_volume', 'betmgm_visitor_volume']
    )
    volume = volume.merge(
        betmgm_volume,
        right_index=True,
        left_index=True,
        how='inner'
    ).astype(float).sort_index()
    # .merge(
    #     betinia_volume,
    #     right_index=True,
    #     left_index=True,
    #     how='inner'
    # )

    return (
        prices,
        volume
    )


def get_best_moneyline_price(
        row:pd.Series,
        selected_providers:list,
        home_away:str='home'
    ):
    providers_moneyline = {}
    for provider in selected_providers:
        if not pd.isna(row[provider + '_moneyline' + '_'+ home_away + '_price']):
            providers_moneyline[provider] = row[provider + '_moneyline' + '_'+ home_away + '_price']

    # Get the maximum total
    try:
        min_price = min(providers_moneyline.values())
    except:
        return None, None
    
    # Get the providers with the maximum total
    min_providers = [provider for provider, price in providers_moneyline.items() if price == min_price]
    if not min_providers:
        return None, None
    
    # Get the provider with the highest odds among those with the maximum total
    min_provider = min_providers[0]
    
    return min_provider, min_price


def arb_calc(
        provider_balance_dict:dict,
        sport:str='nba',
        margin_bound:float=.0,
        volume_bound:float=50.
    ) -> dict:

    selected_providers = list(provider_balance_dict.keys())

    prices, volumes = asyncio.run(
        get_sportsbooks_prices(
            sport=sport,
        )
    )

    prices[['best_home_price_provider', 'best_home_price']] = prices.apply(
        get_best_moneyline_price,
        axis=1,
        result_type='expand',
        selected_providers=selected_providers,
        home_away='home'
    )
    prices[['best_visitor_price_provider', 'best_visitor_price']] = prices.apply(
        get_best_moneyline_price,
        axis=1,
        result_type='expand',
        selected_providers=selected_providers,
        home_away='visitor'
    )

    prices['margin'] = 1 - (prices['best_home_price'] + prices['best_visitor_price']) # if > 0, one have to may more then the payout
    prices['margin'] = prices['margin'].round(4)
    prices = prices[prices['margin'] > margin_bound]

    # perform arbitrage calculations
    arbitrage_games = []
    arbitrage_providers = []
    arbitrage_info = {}

    for i,row in prices.iterrows():

        margin = row['margin']

        visitor_team = row['visitor_team']
        visitor_provider = row['best_visitor_price_provider']
        visitor_price = row['best_visitor_price']

        home_team = row['home_team']
        home_provider = row['best_home_price_provider']
        home_price = row['best_home_price']

        if visitor_provider in ['polymarket','polymarket_v2'] and home_provider in ['polymarket','polymarket_v2']:
            visitor_ccy,home_ccy = 'USD','USD'
        elif visitor_provider in ['polymarket','polymarket_v2'] and home_provider not in ['polymarket','polymarket_v2']:
            visitor_ccy,home_ccy = 'USD','SEK'
        elif visitor_provider not in ['polymarket','polymarket_v2'] and home_provider in ['polymarket','polymarket_v2']:
            visitor_ccy,home_ccy = 'SEK','USD'
        elif visitor_provider not in ['polymarket','polymarket_v2'] and home_provider not in ['polymarket','polymarket_v2']:
            visitor_ccy,home_ccy = 'SEK','SEK'

        # Create a dictionary mapping providers to their volume DataFrames
        provider_volumes = {}
        for provider in selected_providers:
            provider_volumes[provider] = volumes[[f"{provider}_home_volume", f"{provider}_visitor_volume"]].copy()

        # Generalized logic to calculate the largest bet size
        def get_max_target_sek(provider, side, price, balance, row_name):
            if provider in provider_volumes:
                volume_column = f"{provider}_{side}_volume"
                if volume_column in provider_volumes[provider].columns:
                    volume_limit = float(provider_volumes[provider].loc[row_name, volume_column])
                    return min(
                        balance * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1) / price,
                        volume_limit * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1./price) # 1/price beacause betfair is expressed in terms of avaible volume to bet while polymarket is expressed in terms of avaible volume to win (in USD)
                    )
            return balance / price

        # Calculate the largest bet size based on prices and provider limits
        max_visitor_target_sek = get_max_target_sek(visitor_provider, 'visitor', visitor_price, provider_balance_dict[visitor_provider], row.name)
        max_home_target_sek = get_max_target_sek(home_provider, 'home', home_price, provider_balance_dict[home_provider], row.name)
        
        if max_home_target_sek < max_visitor_target_sek:
            limiting_side = 'home'
            target_payout = max_home_target_sek
        else:
            limiting_side = 'visitor'
            target_payout = max_visitor_target_sek

        if visitor_provider == 'polymarket' and home_provider == 'polymarket':
            margin_split = 'split' # 'home' 'visitor'
        elif visitor_provider == 'polymarket' and home_provider != 'polymarket':
            margin_split = 'split'
        elif visitor_provider != 'polymarket' and home_provider == 'polymarket':
            margin_split = 'split'
        else:
            margin_split = 'split'

        # Calculate stake sizes based on the limiting side to decide amounts
        if limiting_side == 'visitor':
            # Visitor side is limiting, set it to max possible
            visitor_stake_sek = target_payout * visitor_price

            if margin_split == 'split': # split profit evenly
                home_stake_sek = target_payout*home_price
            elif margin_split == 'home': # allocate profit to home side (visitor break even)
                home_stake_sek = target_payout*(1-visitor_price)
            elif margin_split == 'visitor': # allocate profit to visitor side (home break even)
                home_stake_sek = visitor_stake_sek/((1./home_price)-1)
        else:
            # Home side is limiting, set it to max possible
            home_stake_sek = target_payout * home_price

            if margin_split == 'split': # split profit evenly
                visitor_stake_sek = target_payout*visitor_price
            elif margin_split == 'visitor': # allocate profit to visitor side (home break even)
                visitor_stake_sek = target_payout*(1-home_price)
            elif margin_split == 'home': # allocate profit to home side (visitor break even)
                visitor_stake_sek = home_stake_sek/((1./visitor_price)-1)
        
        # calculate actual stake
        actual_stake_sek = visitor_stake_sek + home_stake_sek

        # calculate payout
        visitor_payout_sek = visitor_stake_sek*(1./visitor_price)
        home_payout_sek = home_stake_sek*(1./home_price)
        
        # calculate profit in SEK
        visitor_profit_sek = visitor_payout_sek - actual_stake_sek
        home_profit_sek = home_payout_sek - actual_stake_sek

        # calculate profit percentage
        visitor_profit_percentage = (visitor_profit_sek/actual_stake_sek)*100
        home_profit_percentage = (home_profit_sek/actual_stake_sek)*100

        visitor_url = SPORTSBOOKS_URL[visitor_provider]
        home_url = SPORTSBOOKS_URL[home_provider]

        # list arbitrage games
        arbitrage_games.append(row.name)
        game_arbitrage_providers = [visitor_provider,home_provider]
        arbitrage_providers.extend([provider for provider in game_arbitrage_providers if provider not in arbitrage_providers])

        # store arbitrage info
        arbitrage_info[row.name] = {
            # game info
            'margin':margin,
            'actual_stake_sek':actual_stake_sek,
            'usdsek':USDSEK,
            'swe_time':row.swe_time,
            'visitor':{
                # static
                'team':visitor_team,
                'provider':visitor_provider,
                'price':visitor_price,
                'odds':(1./visitor_price),
                'ccy':visitor_ccy,
                'url': visitor_url,
                # calculated
                'stake_sek':visitor_stake_sek,
                'payout_sek':visitor_payout_sek,
                'profit_sek':visitor_profit_sek,
                'profit_percentage':visitor_profit_percentage,
            },
            'home':{
                # static
                'team':home_team,
                'provider':home_provider,
                'price':home_price,
                'odds':(1./home_price),
                'ccy':home_ccy,
                'url': home_url,
                # calculated
                'stake_sek':home_stake_sek,
                'payout_sek':home_payout_sek,
                'profit_sek':home_profit_sek,
                'profit_percentage':home_profit_percentage
            }
        }

    return arbitrage_info