import discord
from discord.ext import commands, tasks
import time
import asyncio
import traceback
import os
import time
import random
from cutgems_utils.get.arbitrage import arbitrage

PROVIDER_INFO = arbitrage.PROVIDER_INFO

# Discord
APPLICATION_KEY = os.getenv("APPLICATION_KEY")
NFL_CHANNEL_ID = int(os.getenv("NFL_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    
    # Debug information
    print("\nServer and Channel Information:")
    for guild in bot.guilds:
        print(f"\nServer: {guild.name} (ID: {guild.id})")
        print("Text Channels:")
        for channel in guild.text_channels:
            print(f"- #{channel.name}: {channel.id}")
    
    channel = bot.get_channel(int(NFL_CHANNEL_ID))
    if channel:
        print(f'\nTarget channel found: #{channel.name}')
        permissions = channel.permissions_for(guild.me)
        print(f'Bot can view channel: {permissions.view_channel}')
        print(f'Bot can send messages: {permissions.send_messages}')
    else:
        print(f'\nERROR: Could not find channel {NFL_CHANNEL_ID}')
        print('Please check:')
        print('1. The bot is invited to the correct server')
        print('2. The channel ID is correct')
        print('3. The bot has permission to view the channel')
    
    check_arbitrage.start()

@tasks.loop(seconds=60.*5.)
async def check_arbitrage():
    try:
        channel = bot.get_channel(NFL_CHANNEL_ID)
        if channel is None:
            print(f'ERROR: Could not find channel {NFL_CHANNEL_ID}')
            return
        
        time.sleep(random.randint(0,9))

        # timeout handling
        async with asyncio.timeout(60):
            arbitrage_dict = await arbitrage.arbitrage_calculation(
                sport="nfl",
                provider_info=PROVIDER_INFO,
                bound=.0
            )

        print(f'checked for arbitrage, time: {time.strftime("%Y-%m-%d %H:%M:%S")}')

        if arbitrage_dict:
            for cat, cat_dict in arbitrage_dict.items():
                if cat == 'moneyline':
                    for game_id, opportunity in cat_dict.items():
                        # Only send message if there's a positive margin
                        if (
                                # high margin -> no profit threshold
                                opportunity['margin'] >= 0.01
                                or
                                # medium margin -> medium profit threshold
                                (opportunity['margin'] >= .005 and (opportunity['visitor']['profit_sek'] > 20 or opportunity['home']['profit_sek'] > 20))
                                or
                                # low margin -> high profit threshold
                                (opportunity['margin'] >= .001 and (opportunity['visitor']['profit_sek'] > 50 or opportunity['home']['profit_sek'] > 50))
                            ):
                            print('sending message')

                            embed = discord.Embed(
                                title="🏆 Moneyline Arbitrage Found!",
                                color=discord.Color.green()
                            )
                            
                            # Game details
                            game_details = (
                                f"**{opportunity['visitor']['team']} @ {opportunity['home']['team']}**\n"
                                f"Start Time {opportunity['swe_time']}\n"
                                f"Margin: {opportunity['margin']*100:.2f}%\n"
                                f"Total Stake: {opportunity['actual_stake_sek']:,.2f} SEK"
                            )
                            embed.add_field(name="Game Details", value=game_details, inline=False)
                            
                            # Visitor bet details
                            visitor_stake_sek = opportunity['visitor']['stake_sek']
                            visitor_payout_sek = opportunity['visitor']['payout_sek']
                            
                            if opportunity['visitor']['ccy'] == 'USD':
                                visitor_bet_str = f"${(visitor_stake_sek/opportunity['usdsek']):,.2f} ({visitor_stake_sek:,.2f} SEK)"
                                visitor_payout_str = f"${(visitor_payout_sek/opportunity['usdsek']):,.2f} ({visitor_payout_sek:,.2f} SEK)"
                            else:
                                visitor_bet_str = f"{visitor_stake_sek:,.2f} SEK"
                                visitor_payout_str = f"{visitor_payout_sek:,.2f} SEK"
                            
                            visitor_details = (
                                f"Provider: {opportunity['visitor']['provider']}\n"
                                f"Odds: {opportunity['visitor']['odds']:.3f}\n"
                                f"Price: {opportunity['visitor']['price']:.3f}\n"
                                f"Bet Size: {visitor_bet_str}\n"
                                f"Potential Payout: {visitor_payout_str}\n"
                                f"Potential Profit: {opportunity['visitor']['profit_sek']:,.2f} SEK ({opportunity['visitor']['profit_percentage']:.2f}%)\n"
                                f"link: {opportunity['visitor']['url']}"
                            )
                            embed.add_field(
                                name=f"Bet 1: {opportunity['visitor']['team']}", 
                                value=visitor_details, 
                                inline=True
                            )
                            
                            # Format home bet size and payout with currency conversion if needed
                            home_stake_sek = opportunity['home']['stake_sek']
                            home_payout_sek = opportunity['home']['payout_sek']
                            
                            if opportunity['home']['ccy'] == 'USD':
                                home_bet_str = f"${(home_stake_sek/opportunity['usdsek']):,.2f} ({home_stake_sek:,.2f} SEK)"
                                home_payout_str = f"${(home_payout_sek/opportunity['usdsek']):,.2f} ({home_payout_sek:,.2f} SEK)"
                            else:
                                home_bet_str = f"{home_stake_sek:,.2f} SEK"
                                home_payout_str = f"{home_payout_sek:,.2f} SEK"
                            
                            home_details = (
                                f"Provider: {opportunity['home']['provider']}\n"
                                f"Odds: {opportunity['home']['odds']:.3f}\n"
                                f"Price: {opportunity['home']['price']:.3}\n"
                                f"Bet Size: {home_bet_str}\n"
                                f"Potential Payout: {home_payout_str}\n"
                                f"Potential Profit: {opportunity['home']['profit_sek']:,.2f} SEK ({opportunity['home']['profit_percentage']:.2f}%)\n"
                                f"link: {opportunity['home']['url']}"
                            )
                            embed.add_field(
                                name=f"Bet 2: {opportunity['home']['team']}", 
                                value=home_details, 
                                inline=True
                            )
                            
                            # Add timestamp
                            embed.timestamp = discord.utils.utcnow()
                            
                            try:
                                await channel.send(embed=embed)
                            except discord.errors.Forbidden:
                                print(f'ERROR: Bot does not have permission to send messages in #{channel.name}')
                            except Exception as e:
                                print(f'ERROR: Failed to send message: {str(e)}')
                
                elif cat == 'spread':
                    for game_id, game_dict in cat_dict.items():
                        for line, opportunity in game_dict.items():


                            # Only send message if there's a positive margin
                            if (
                                    # high margin -> no profit threshold
                                    opportunity['margin'] >= 0.01
                                    or
                                    # medium margin -> medium profit threshold
                                    (opportunity['margin'] >= .005 and (opportunity['visitor']['profit_sek'] > 20 or opportunity['home']['profit_sek'] > 20))
                                    or
                                    # low margin -> high profit threshold
                                    (opportunity['margin'] >= .001 and (opportunity['visitor']['profit_sek'] > 50 or opportunity['home']['profit_sek'] > 50))
                                ):
                                print('sending message')

                                embed = discord.Embed(
                                    title="↔️ Spread Arbitrage Found!",
                                    color=discord.Color.green()
                                )
                                
                                # Game details
                                game_details = (
                                    f"**{opportunity['visitor']['team']} @ {opportunity['home']['team']}**\n"
                                    f"*Line: {line}*\n"
                                    f"Start Time {opportunity['swe_time']}\n"
                                    f"Margin: {opportunity['margin']*100:.2f}%\n"
                                    f"Total Stake: {opportunity['actual_stake_sek']:,.2f} SEK"
                                )
                                embed.add_field(name="Game Details", value=game_details, inline=False)
                                
                                # Visitor bet details
                                visitor_stake_sek = opportunity['visitor']['stake_sek']
                                visitor_payout_sek = opportunity['visitor']['payout_sek']
                                
                                if opportunity['visitor']['ccy'] == 'USD':
                                    visitor_bet_str = f"${(visitor_stake_sek/opportunity['usdsek']):,.2f} ({visitor_stake_sek:,.2f} SEK)"
                                    visitor_payout_str = f"${(visitor_payout_sek/opportunity['usdsek']):,.2f} ({visitor_payout_sek:,.2f} SEK)"
                                else:
                                    visitor_bet_str = f"{visitor_stake_sek:,.2f} SEK"
                                    visitor_payout_str = f"{visitor_payout_sek:,.2f} SEK"
                                
                                visitor_details = (
                                    f"Line: {-line}\n"
                                    f"Provider: {opportunity['visitor']['provider']}\n"
                                    f"Odds: {opportunity['visitor']['odds']:.3f}\n"
                                    f"Price: {opportunity['visitor']['price']:.3f}\n"
                                    f"Bet Size: {visitor_bet_str}\n"
                                    f"Potential Payout: {visitor_payout_str}\n"
                                    f"Potential Profit: {opportunity['visitor']['profit_sek']:,.2f} SEK ({opportunity['visitor']['profit_percentage']:.2f}%)\n"
                                    f"link: {opportunity['visitor']['url']}"
                                )
                                embed.add_field(
                                    name=f"Bet 1: {opportunity['visitor']['team']}", 
                                    value=visitor_details, 
                                    inline=True
                                )
                                
                                # Format home bet size and payout with currency conversion if needed
                                home_stake_sek = opportunity['home']['stake_sek']
                                home_payout_sek = opportunity['home']['payout_sek']
                                
                                if opportunity['home']['ccy'] == 'USD':
                                    home_bet_str = f"${(home_stake_sek/opportunity['usdsek']):,.2f} ({home_stake_sek:,.2f} SEK)"
                                    home_payout_str = f"${(home_payout_sek/opportunity['usdsek']):,.2f} ({home_payout_sek:,.2f} SEK)"
                                else:
                                    home_bet_str = f"{home_stake_sek:,.2f} SEK"
                                    home_payout_str = f"{home_payout_sek:,.2f} SEK"
                                
                                home_details = (
                                    f"Line: {line}\n"
                                    f"Provider: {opportunity['home']['provider']}\n"
                                    f"Odds: {opportunity['home']['odds']:.3f}\n"
                                    f"Price: {opportunity['home']['price']:.3}\n"
                                    f"Bet Size: {home_bet_str}\n"
                                    f"Potential Payout: {home_payout_str}\n"
                                    f"Potential Profit: {opportunity['home']['profit_sek']:,.2f} SEK ({opportunity['home']['profit_percentage']:.2f}%)\n"
                                    f"link: {opportunity['home']['url']}"
                                )
                                embed.add_field(
                                    name=f"Bet 2: {opportunity['home']['team']}", 
                                    value=home_details, 
                                    inline=True
                                )
                                
                                # Add timestamp
                                embed.timestamp = discord.utils.utcnow()
                                
                                try:
                                    await channel.send(embed=embed)
                                except discord.errors.Forbidden:
                                    print(f'ERROR: Bot does not have permission to send messages in #{channel.name}')
                                except Exception as e:
                                    print(f'ERROR: Failed to send message: {str(e)}')

                elif cat == 'total':
                    for game_id, game_dict in cat_dict.items():
                        for line, opportunity in game_dict.items():

                            # Only send message if there's a positive margin
                            if (
                                    # high margin -> no profit threshold
                                    opportunity['margin'] >= 0.01
                                    or
                                    # medium margin -> medium profit threshold
                                    (opportunity['margin'] >= .005 and (opportunity['visitor']['profit_sek'] > 20 or opportunity['home']['profit_sek'] > 20))
                                    or
                                    # low margin -> high profit threshold
                                    (opportunity['margin'] >= .001 and (opportunity['visitor']['profit_sek'] > 50 or opportunity['home']['profit_sek'] > 50))
                                ):
                                print('sending message')

                                embed = discord.Embed(
                                    title="📊 Total Arbitrage Found!",
                                    color=discord.Color.green()
                                )
                                
                                # Game details
                                game_details = (
                                    f"**{opportunity['visitor']['team']} @ {opportunity['home']['team']}**\n"
                                    f"*Line: {line}*\n"
                                    f"Start Time {opportunity['swe_time']}\n"
                                    f"Margin: {opportunity['margin']*100:.2f}%\n"
                                    f"Total Stake: {opportunity['actual_stake_sek']:,.2f} SEK"
                                )
                                embed.add_field(name="Game Details", value=game_details, inline=False)
                                
                                # Visitor bet details
                                visitor_stake_sek = opportunity['visitor']['stake_sek']
                                visitor_payout_sek = opportunity['visitor']['payout_sek']
                                
                                if opportunity['visitor']['ccy'] == 'USD':
                                    visitor_bet_str = f"${(visitor_stake_sek/opportunity['usdsek']):,.2f} ({visitor_stake_sek:,.2f} SEK)"
                                    visitor_payout_str = f"${(visitor_payout_sek/opportunity['usdsek']):,.2f} ({visitor_payout_sek:,.2f} SEK)"
                                else:
                                    visitor_bet_str = f"{visitor_stake_sek:,.2f} SEK"
                                    visitor_payout_str = f"{visitor_payout_sek:,.2f} SEK"
                                
                                visitor_details = (
                                    f"Provider: {opportunity['visitor']['provider']}\n"
                                    f"Odds: {opportunity['visitor']['odds']:.3f}\n"
                                    f"Price: {opportunity['visitor']['price']:.3f}\n"
                                    f"Bet Size: {visitor_bet_str}\n"
                                    f"Potential Payout: {visitor_payout_str}\n"
                                    f"Potential Profit: {opportunity['visitor']['profit_sek']:,.2f} SEK ({opportunity['visitor']['profit_percentage']:.2f}%)\n"
                                    f"link: {opportunity['visitor']['url']}"
                                )
                                embed.add_field(
                                    name=f"Bet 1: {opportunity['visitor']['team']}", 
                                    value=visitor_details, 
                                    inline=True
                                )
                                
                                # Format home bet size and payout with currency conversion if needed
                                home_stake_sek = opportunity['home']['stake_sek']
                                home_payout_sek = opportunity['home']['payout_sek']
                                
                                if opportunity['home']['ccy'] == 'USD':
                                    home_bet_str = f"${(home_stake_sek/opportunity['usdsek']):,.2f} ({home_stake_sek:,.2f} SEK)"
                                    home_payout_str = f"${(home_payout_sek/opportunity['usdsek']):,.2f} ({home_payout_sek:,.2f} SEK)"
                                else:
                                    home_bet_str = f"{home_stake_sek:,.2f} SEK"
                                    home_payout_str = f"{home_payout_sek:,.2f} SEK"
                                
                                home_details = (
                                    f"Provider: {opportunity['home']['provider']}\n"
                                    f"Odds: {opportunity['home']['odds']:.3f}\n"
                                    f"Price: {opportunity['home']['price']:.3}\n"
                                    f"Bet Size: {home_bet_str}\n"
                                    f"Potential Payout: {home_payout_str}\n"
                                    f"Potential Profit: {opportunity['home']['profit_sek']:,.2f} SEK ({opportunity['home']['profit_percentage']:.2f}%)\n"
                                    f"link: {opportunity['home']['url']}"
                                )
                                embed.add_field(
                                    name=f"Bet 2: {opportunity['home']['team']}", 
                                    value=home_details, 
                                    inline=True
                                )
                                
                                # Add timestamp
                                embed.timestamp = discord.utils.utcnow()
                                
                                try:
                                    await channel.send(embed=embed)
                                except discord.errors.Forbidden:
                                    print(f'ERROR: Bot does not have permission to send messages in #{channel.name}')
                                except Exception as e:
                                    print(f'ERROR: Failed to send message: {str(e)}')




        else: # Sleep a bit longer if no arbitrage opportunities found
            # time.sleep(60.*5.)
            pass

    except asyncio.TimeoutError:
        print("Arbitrage check timed out after 30 seconds")
    except Exception as e:
        print(f"Error in check_arbitrage: {str(e)}")
        traceback.print_exc()
        
bot.run(APPLICATION_KEY)