import streamlit as st
import pandas as pd
import asyncio
import os
import traceback
import cutgems_utils.get as get
from cutgems_utils.get.arbitrage import arbitrage

PROVIDER_INFO = arbitrage.PROVIDER_INFO
SPORT = 'nfl'
OVERRIDES = {}

os.environ['PHANTOM_PRIVATE_KEY'] = st.secrets['PHANTOM_PRIVATE_KEY']
os.environ['POLYMARKET_PUBLIC_KEY'] = st.secrets['POLYMARKET_PUBLIC_KEY']

st.set_page_config(
    page_title='Arbitrage',
    page_icon=':heavy_dollar_sign:',
    layout='wide',
    # initial_sidebar_state="collapsed"
)

col1,col2 = st.columns([1,1])

selected_providers = col1.pills(
    key="selected_providers",
    label="Select Providers",
    options=PROVIDER_INFO.keys(),
    default=PROVIDER_INFO.keys(),
    selection_mode="multi"
)

PROVIDER_INFO = {k: v for k, v in PROVIDER_INFO.items() if k in selected_providers}

@st.cache_data(ttl=60*5)
def get_prices(sport:str='nba'):
    return asyncio.run(
        arbitrage.combine_sportbooks_prices(
            sport=sport,
            overrides=OVERRIDES,
            provider_info=PROVIDER_INFO
        )
    )

if st.button('Update Odds'):
    get_prices.clear()

@st.cache_data(ttl=60*5)
def get_usdsek():
    return get.usdsek()

USDSEK = get_usdsek()
USDSEK = col2.number_input(
    label='USD/SEK',
    value=USDSEK,
    step=0.01,
    key='USDSEK'
)

data = get_prices(sport=SPORT)
info = data['info']
price_dict = data['price']
volume_dict = data['volume']

cols = st.columns(len(st.session_state['selected_providers']))

for idx, provider in enumerate(st.session_state['selected_providers']):
    if provider in ['polymarket','polymarket_v2']:
        PROVIDER_INFO[provider]['balance'] = cols[idx].number_input(
            label=f'{provider} Limit (USD)',
            value=PROVIDER_INFO[provider]['balance'],
            min_value=0.,
            max_value=100_000.,
            step=10.,
            key=f'{provider}_limit'
        )
    else:
        PROVIDER_INFO[provider]['balance'] = cols[idx].number_input(
            label=f'{provider} Limit (SEK)',
            value=PROVIDER_INFO[provider]['balance'],
            min_value=0.,
            max_value=1_000_000.,
            step=100.,
            key=f'{provider}_limit'
        )

tabs = st.tabs(list(price_dict.keys()))
tab_idx = 0
for cat, price in price_dict.items():

    price = price.set_index('game_id').sort_values('margin',ascending=False)
    price = price.loc[price['margin'] >= -0.02]
    price = price.loc[price.index.isin(info.loc[info['state']=='NOT_STARTED'].index)]
    volume = volume_dict[cat].set_index('game_id')

    with tabs[tab_idx]:

        # st.write(price)
        # st.write(volume)

        for i,row in price.iterrows():

            try:

                margin = row['margin']*100

                if cat == 'total': # UNDER = VISITOR
                    visitor_team = 'Under'
                    visitor_provider = row[f'best_{cat}_under_price_provider']
                    visitor_price = row[f'best_{cat}_under_price']
                else:
                    visitor_team = info.loc[i]['visitor_team']
                    visitor_provider = row[f'best_{cat}_visitor_price_provider']
                    visitor_price = row[f'best_{cat}_visitor_price']
                
                if cat == 'total': # OVER = HOME
                    home_team = 'Over'
                    home_provider = row[f'best_{cat}_over_price_provider']
                    home_price = row[f'best_{cat}_over_price']
                else:
                    home_team = info.loc[i]['home_team']
                    home_provider = row[f'best_{cat}_home_price_provider']
                    home_price = row[f'best_{cat}_home_price']
                
                if cat == 'moneyline':
                    line = 0.
                if cat == 'spread':
                    line = row[f"spread_home"]
                if cat == 'total':
                    line = row[f"total"]

                if visitor_provider in ['polymarket','polymarket_v2'] and home_provider in ['polymarket','polymarket_v2']:
                    visitor_ccy,home_ccy = 'USD','USD'
                elif visitor_provider in ['polymarket','polymarket_v2'] and home_provider not in ['polymarket','polymarket_v2']:
                    visitor_ccy,home_ccy = 'USD','SEK'
                elif visitor_provider not in ['polymarket','polymarket_v2'] and home_provider in ['polymarket','polymarket_v2']:
                    visitor_ccy,home_ccy = 'SEK','USD'
                elif visitor_provider not in ['polymarket','polymarket_v2'] and home_provider not in ['polymarket','polymarket_v2']:
                    visitor_ccy,home_ccy = 'SEK','SEK'

                if cat == 'total':
                    st.header(f'{row.name}:   {visitor_team} @ {home_team} - Total: {line}')
                else:
                    st.header(f'{row.name}:   {visitor_team} @ {home_team}')
                st.subheader(f'Start Time: {info.loc[i]["swe_time"]}')

                col1,col2,col3,col4,col5 = st.columns([2,1,2,2,1])
                col1.header(f'{margin:.2f}%')

                def get_max_target_sek(
                        provider,
                        cat,
                        side,
                        price,
                        balance,
                        index,
                        line=None,
                    ):

                    try:
                        if cat == 'moneyline':
                            volume_limit = float(volume.loc[index, f"{provider}_{cat}_{side}_volume"])
                            return min(
                                balance * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1.) / price,
                                volume_limit * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1./price) # 1/price beacause betfair is expressed in terms of avaible volume to bet while polymarket is expressed in terms of avaible volume to win (in USD)
                            )
                        elif cat == 'spread':
                            volume_limit = volume.loc[index]
                            volume_limit = float(volume_limit.loc[volume_limit[f"{cat}_{side}"] == line, f"{provider}_{cat}_{side}_volume"].iloc[0])
                            return min(
                                balance * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1.) / price,
                                volume_limit * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1./price) # 1/price beacause betfair is expressed in terms of avaible volume to bet while polymarket is expressed in terms of avaible volume to win (in USD)
                            )
                        elif cat == 'total':
                            volume_limit = volume.loc[index]
                            volume_limit = float(volume_limit.loc[volume_limit[f"{cat}"] == line, f"{provider}_{cat}_{side}_volume"].iloc[0])
                            return min(
                                balance * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1.) / price,
                                volume_limit * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1./price) # 1/price beacause betfair is expressed in terms of avaible volume to bet while polymarket is expressed in terms of avaible volume to win (in USD)
                            )
                    except:
                        return balance * (USDSEK if provider in ['polymarket', 'polymarket_v2'] else 1.) / price

                    # Calculate the largest bet size based on prices and provider limits
                if cat == 'total':
                    max_visitor_target_sek = get_max_target_sek(
                        provider=visitor_provider,
                        cat=cat,
                        side='under',
                        line=row[f"{cat}"],
                        price=visitor_price,
                        balance=PROVIDER_INFO[visitor_provider]['balance'],
                        index=row.name
                    )
                    max_home_target_sek = get_max_target_sek(
                        provider=home_provider,
                        cat=cat,
                        side='over',
                        line=row[f"{cat}"],
                        price=home_price,
                        balance=PROVIDER_INFO[home_provider]['balance'],
                        index=row.name
                    )
                elif cat == 'spread':
                    max_visitor_target_sek = get_max_target_sek(
                        provider=visitor_provider,
                        cat=cat,
                        side='visitor',
                        line=row[f"{cat}_visitor"],
                        price=visitor_price,
                        balance=PROVIDER_INFO[visitor_provider]['balance'],
                        index=row.name
                    )
                    max_home_target_sek = get_max_target_sek(
                        provider=home_provider,
                        cat=cat,
                        side='home',
                        line=row[f"{cat}_home"],
                        price=home_price,
                        balance=PROVIDER_INFO[home_provider]['balance'],
                        index=row.name
                    )
                elif cat == 'moneyline':
                    max_visitor_target_sek = get_max_target_sek(
                        provider=visitor_provider,
                        cat=cat,
                        side='visitor',
                        price=visitor_price,
                        balance=PROVIDER_INFO[visitor_provider]['balance'],
                        index=row.name
                    )
                    max_home_target_sek = get_max_target_sek(
                        provider=home_provider,
                        cat=cat,
                        side='home',
                        price=home_price,
                        balance=PROVIDER_INFO[home_provider]['balance'],
                        index=row.name
                    )
                    
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
                    key=f'bet_size_{i}_{line}'
                )

                margin_split_options = ['split','visitor','home']
                margin_split = col2.radio(
                    label='Margin Split',
                    options=margin_split_options,
                    key=f'margin_split_{i}_{line}'
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

                visitor_url = PROVIDER_INFO[visitor_provider]['url']['mlb']
                home_url = PROVIDER_INFO[home_provider]['url']['mlb']

                col1.write(f'(Actual Stake: {actual_stake_sek:.2f} SEK)')

                # VISITOR INFO
                if cat == 'spread':
                    col3.subheader(f'{visitor_team} {row[f"{cat}_visitor"]} ({visitor_provider})')
                else:
                    col3.subheader(f'{visitor_team} ({visitor_provider})')
                if visitor_provider in ['polymarket','polymarket_v2']:
                    col3.subheader(f'Bet Size: {visitor_stake_sek/USDSEK:.2f} USD ({visitor_stake_sek:.2f} SEK)')
                else:
                    col3.subheader(f'Bet Size: {visitor_stake_sek:.2f} SEK')
                col3.subheader(f'Price/Odds: {visitor_price:.3f} / {(1./visitor_price):.3f}')
                if visitor_provider in ['polymarket','polymarket_v2']:
                    col3.subheader(f'Payout: {visitor_payout_sek/USDSEK:.2f} USD ({visitor_payout_sek:.2f} SEK)')
                else:
                    col3.subheader(f'Payout: {visitor_payout_sek:.2f} SEK')
                col3.subheader(f'Profit: {visitor_profit_sek:.2f} SEK ({visitor_profit_percentage:.2f}%)')
                col3.write(f'Visitor URL: [{visitor_provider}]({visitor_url})')

                # HOME INFO
                if cat == 'spread':
                    col4.subheader(f'{home_team} {row[f"{cat}_home"]} ({home_provider})')
                else:
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
                # st.warning(traceback.format_exc())
                pass

            st.divider()
    tab_idx+=1
