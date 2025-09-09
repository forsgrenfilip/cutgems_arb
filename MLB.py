import streamlit as st
import pandas as pd
import asyncio
import os
import traceback
import arb_calc
import cutgems_utils.get as get
from sportsbooks_info import(
    SPORTSBOOKS_BALANCES,
    SPORTSBOOKS_URL
)

os.environ['PHANTOM_PRIVATE_KEY'] = st.secrets['PHANTOM_PRIVATE_KEY']
os.environ['POLYMARKET_PUBLIC_KEY'] = st.secrets['POLYMARKET_PUBLIC_KEY']

st.set_page_config(
    page_title='Arbitrage',
    page_icon=':heavy_dollar_sign:',
    layout='wide',
    # initial_sidebar_state="collapsed"
)

@st.cache_data(ttl=60*5)
def get_prices():
    return asyncio.run(
        arb_calc.get_sportsbooks_prices(
            sport='mlb'
        )
    )

@st.cache_data(ttl=60*5)
def get_usdsek():
    return get.usdsek()
USDSEK = get_usdsek()

def get_best_moneyline_price(
        row,
        selected_providers,
        home_away='home'
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

col1,col2 = st.columns([1,1])

selected_providers = col1.pills(
    key="selected_providers",
    label="Select Providers",
    options=SPORTSBOOKS_BALANCES.keys(),
    default=SPORTSBOOKS_BALANCES.keys(),
    selection_mode="multi"
)

USDSEK = col2.number_input(
    label='USD/SEK',
    value=USDSEK,
    step=0.01,
    key='USDSEK'
)

if st.button('Update Odds'):
    get_prices.clear()


prices, volumes = get_prices()

# st.dataframe(prices)
# st.dataframe(volumes)

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
prices = prices.sort_values('margin', ascending=False)

prices = prices.loc[prices['state'] != 'STARTED']

cols = st.columns(len(st.session_state['selected_providers']))

for idx, provider in enumerate(st.session_state['selected_providers']):
    if provider in ['polymarket','polymarket_v2']:
        SPORTSBOOKS_BALANCES[provider] = cols[idx].number_input(
            label=f'{provider} Limit (USD)',
            value=SPORTSBOOKS_BALANCES[provider],
            min_value=0.,
            max_value=100_000.,
            step=10.,
            key=f'{provider}_limit'
        )
    else:
        SPORTSBOOKS_BALANCES[provider] = cols[idx].number_input(
            label=f'{provider} Limit (SEK)',
            value=SPORTSBOOKS_BALANCES[provider],
            min_value=0.,
            max_value=1_000_000.,
            step=100.,
            key=f'{provider}_limit'
        )


for i,row in prices.iterrows():

    try:

        margin = row['margin']*100

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

        st.header(f'{row.name}:   {visitor_team} @ {home_team}')
        st.subheader(f'Start Time: {row["swe_time"]}')

        col1,col2,col3,col4,col5 = st.columns([2,1,2,2,1])
        col1.header(f'{margin:.2f}%')

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
        max_visitor_target_sek = get_max_target_sek(visitor_provider, 'visitor', visitor_price, SPORTSBOOKS_BALANCES[visitor_provider], row.name)
        max_home_target_sek = get_max_target_sek(home_provider, 'home', home_price, SPORTSBOOKS_BALANCES[home_provider], row.name)
        
        if max_home_target_sek < max_visitor_target_sek:
            limiting_side = 'home'
            max_target_payout = max_home_target_sek
        else:
            limiting_side = 'visitor'
            max_target_payout = max_visitor_target_sek

        target_payout = col1.number_input(
            label='Bet Size',
            min_value=0.,
            value=max_target_payout,
            step=100.,
            key=f'bet_size_{i}'
        )

        margin_split_options = ['split','visitor','home']
        margin_split = col2.radio(
            label='Margin Split',
            options=margin_split_options,
            key=f'margin_split_{i}'
        )

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

        col1.write(f'(Actual Stake: {actual_stake_sek:.2f} SEK)')

        col3.subheader(f'{visitor_team} ({visitor_provider})')
        if visitor_provider in ['polymarket','polymarket_v2']:
            col3.subheader(f'Bet Size: {visitor_stake_sek/USDSEK:.2f} USD ({visitor_stake_sek:.2f} SEK)')
        else:
            col3.subheader(f'Bet Size: {visitor_stake_sek:.2f} SEK')
        col3.subheader(f'Price/Odds: {visitor_price:.3f} / {(1./visitor_price):.3f}')
        # col3.subheader(f'Odds: {visitor_odds:.2f}')
        if visitor_provider in ['polymarket','polymarket_v2']:
            col3.subheader(f'Payout: {visitor_payout_sek/USDSEK:.2f} USD ({visitor_payout_sek:.2f} SEK)')
        else:
            col3.subheader(f'Payout: {visitor_payout_sek:.2f} SEK')
        col3.subheader(f'Profit: {visitor_profit_sek:.2f} SEK ({visitor_profit_percentage:.2f}%)')
        col3.write(f'Visitor URL: [{visitor_provider}]({visitor_url})')

        col4.subheader(f'{home_team} ({home_provider})')
        if home_provider in ['polymarket','polymarket_v2']:
            col4.subheader(f'Bet Size: {home_stake_sek/USDSEK:.2f} USD ({home_stake_sek:.2f} SEK)')
        else:
            col4.subheader(f'Bet Size: {home_stake_sek:.2f}')
        col4.subheader(f'Price/Odds: {home_price:.3f} / {(1./home_price):.3f}')
        # col4.subheader(f'Odds: {home_odds:.3f}')
        if home_provider in ['polymarket','polymarket_v2']:
            col4.subheader(f'Payout: {home_payout_sek/USDSEK:.2f} USD ({home_payout_sek:.2f} SEK)')
        else:
            col4.subheader(f'Payout: {home_payout_sek:.2f} SEK')
        col4.subheader(f'Profit: {home_profit_sek:.2f} SEK ({home_profit_percentage:.2f}%)')
        col4.write(f'Home URL: [{home_provider}]({home_url})')
    
    except:
        st.warning(traceback.format_exc())

    st.divider()

st.dataframe(prices)
st.dataframe(volumes)