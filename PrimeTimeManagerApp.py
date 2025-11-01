#!/usr/bin/env python3
import os
import platform
import sys
import time
from datetime import date, datetime, timedelta
import calendar
from utils.logger import Logger
from utils.source import LoadData
import webbrowser 

def initialLogger(log):
    log.registerStack("config")

    log.registerStack("general")
    log.appendItemToStack("general", "General:")

    log.registerStack("future_title")
    log.appendItemToStack("future_title", "Title with date in future:")

    log.registerStack("show_all")
    log.appendItemToStack("show_all", "Show all:")

    log.registerStack("show_simulcast")
    log.appendItemToStack("show_simulcast", "Show simulcast:")

    log.registerStack("show_simulcast_past")
    log.appendItemToStack("show_simulcast_past", "Show simulcast additional past:")

    log.registerStack("show_simulcast_future")
    log.appendItemToStack("show_simulcast_future", "Show simulcast additional future:")

    log.registerStack("show_wildcard")
    log.appendItemToStack("show_wildcard", "Show wildcard:")

    log.registerStack("skipped_wildcard")
    log.appendItemToStack("skipped_wildcard", "Show wildcard:")

def openURL(url):
    for i, url in enumerate(url):
        if i == 0:
            webbrowser.open_new(url)
            time.sleep(1)
        else:
            webbrowser.open_new_tab(url)

def dateConvert(dateNumber):
    return calendar.day_name[dateNumber]

def showSimulcast(log, data, item, url):
    simulcastDate = data.getWatchlistValue(item, "Date")
    if (simulcastDate.weekday() == date.today().weekday()):
        log.appendItemToStack("show_simulcast", f"{item["Name"]} ({dateConvert(item["Date"].weekday())}): {item["URL"]}")
        url.append(item["URL"])

    if data.getConfigValue("showSimulcastAdditionalPast"): 
        for offset in range(1, int(data.getConfigValue("showSimulcastDaysPast")) + 1):
            if simulcastDate.weekday() == (date.today() - timedelta(days=offset)).weekday():
                log.appendItemToStack("show_simulcast_past", f'{item["Name"]} ({dateConvert(item["Date"].weekday())}): {item["URL"]}')
                url.append(item["URL"])

    if data.getConfigValue("showSimulcastAdditionalFuture"): 
        for offset in range(1, int(data.getConfigValue("showSimulcastDaysFuture")) + 1):
            if simulcastDate.weekday() == (date.today() + timedelta(days=offset)).weekday():
                log.appendItemToStack("show_simulcast_future", f'{item["Name"]} ({dateConvert(item["Date"].weekday())}): {item["URL"]}')
                url.append(item["URL"])

def main(): 
    log = Logger()
    initialLogger(log)

    data = LoadData(log)
    config = data.config
    watchlist = data.watchlist
    url = []

    for item in watchlist:
        simulcastDate = data.getWatchlistValue(item, "Date")
        simulcastDelta = timedelta(weeks=int(data.getWatchlistValue(item, "Episodes")))
      
        if data.getWatchlistValue(item, "Episodes") == -1 and not data.getConfigValue("showWildcard"):
            log.appendItemToStack("skipped_wildcard", f"{item["Name"]} ({item["Date"]}/{item["Episodes"]}/{item["RANK"]})")
            continue
        elif data.getWatchlistValue(item, "Episodes") == -1 and data.getConfigValue("showWildcard"): 
            log.appendItemToStack("show_wildcard", f"{item["Name"]} ({item["Episodes"]}): {item["URL"]}")
            url.append(item["URL"])
            continue

        # Titel should be shown in simulcast
        if (simulcastDate + simulcastDelta) >= date.today():
            # only simulcast is active
            if data.getConfigValue("showSimulcast"):
                showSimulcast(log, data, item, url)
                
            # show all title
            if data.getConfigValue("showAll"):
                # show simulcast if not already shown by config showSimulcast
                if not data.getConfigValue("showSimulcast"):
                    showSimulcast(log, data, item, url)

                # show every else than simulcast
                if not (simulcastDate.weekday() == date.today().weekday()):

                    # skip additional days in showAll 
                    skip = False
                    if data.getConfigValue("showSimulcastAdditionalPast"):
                        for offset in range(1, int(data.getConfigValue("showSimulcastDaysPast")) + 1):
                            if simulcastDate.weekday() == (date.today() - timedelta(days=offset)).weekday():
                                skip = True

                    if skip:
                        continue                                
            
                    if data.getConfigValue("showSimulcastAdditionalFuture"):
                        for offset in range(1, int(data.getConfigValue("showSimulcastDaysFuture")) + 1):
                            if simulcastDate.weekday() == (date.today() + timedelta(days=offset)).weekday():
                                skip = True

                    if skip:
                        continue

                    log.appendItemToStack("show_all", f"{item["Name"]} ({dateConvert(item["Date"].weekday())}): {item["URL"]}")
                    url.append(item["URL"])

    if not data.getConfigValue("showAll") and not data.getConfigValue("showSimulcast"): 
        log.appendItemToStack("general", "Nothing to do ...")
    
    openURL(url)
    
    log.printLogging(config)
    if data.getConfigValue("printDebugToConsole"):
        try:
            input("Press [Enter], to stop the app while holding consol screen (otherwise [Ctrl+C] to cancel)")
        except KeyboardInterrupt:
            print("\nApplication canceled.")

            if (platform.system() == str(data.getConfigValue("platform")).capitalize() ):
                os.system("exit")
            else: 
                sys.exit(0)
    else: 
        if (platform.system() == str(data.getConfigValue("platform")).capitalize() ):
            os.system("exit")
        else: 
            sys.exit(0)
    
if __name__ == '__main__':
    main()
    