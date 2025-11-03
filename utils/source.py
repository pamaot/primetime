import re
import platform
import os
import sys
from datetime import date
from pathlib import Path

def normalizeString(config):
    return str(config).replace("\n", "").replace("\r", "").replace("\t", "").strip()

class LoadData():
    def __init__(self, log):
        self.BASE_DIR = Path(__file__).resolve().parent.parent
        self.log = log
        self.config = {}
        self.watchlist = []
        self.url = []
        self.loadConfigDict()
        self.loadWatchDict()

    def getFile(self, file, fileDev):
        try:
            return file.resolve(strict=True)
        except FileNotFoundError:
            print(f"File: {file} not found")
            try:
                print(f"Trying: {fileDev}")
                return fileDev.resolve(strict=True)
            except FileNotFoundError:
                print(f"File: {fileDev} not found")
                print("PrimeTimeManager can't work without definition")
                try:
                    input("Press [Enter], to stop the app while holding console screen (otherwise [Ctrl+C] to cancel)")
                except KeyboardInterrupt:
                    print("\nApplication canceled.")
                    if (platform.system() == str(data.getConfigValue("platform")).capitalize() ):
                        os.system("exit")
                    else: 
                        sys.exit(0)

    def replaceElementsWhiteSpace(self, elem):
        for index, e in enumerate(elem):
            elem[index] = e.replace(" ", "")
        return elem
    
    def parseDate(self, dateObject):    
        # config
        seperator = self.getConfigValue("dateSeperatorAllowed").split(",")
        pattern = f"[{''.join(map(re.escape, seperator))}]"
        
        formats = re.split(",", self.getConfigValue("dateFormats"))
        formatUsed = formats[int(self.getConfigValue("dateFormatUse"))-1]

        dateSegmentsFormat = re.split(pattern, formatUsed)
        dateSegments = re.split(pattern, dateObject)

        year = int(dateSegments[dateSegmentsFormat.index("y")])
        if int(year) < 100:
            year = int(year) + 2000 
       
        month = int(dateSegments[dateSegmentsFormat.index("m")])
        day = int(dateSegments[dateSegmentsFormat.index("d")])
                  
        d = date(year, month, day)

        return d

    def loadConfigDict(self):
        configPath = self.BASE_DIR / "config.txt"
        configDevPath = self.BASE_DIR / "PrimeTimeManagerConfig.dev.txt"
        config = {}
        configfile = open(self.getFile(configPath, configDevPath), 'r')

        for line in configfile: 
            if not line.strip() or line.startswith("#"): 
                continue

            elem = line.split("=")
            elem = self.replaceElementsWhiteSpace(elem)
            
            for index, e in enumerate(elem): 
                elem[index] = normalizeString(e)

            result = elem[1]
            if "true" == str(result.lower()):
                elem[1] = True
            elif "false" == str(result.lower()):
                elem[1] = False

            config.update({elem[0] : elem[1]})
        self.config = config
    
    def loadWatchDict(self):
        watchlistPath = self.BASE_DIR / "watchlist.txt"
        watchlistDevPath = self.BASE_DIR / "/PrimeTimeManagerWatchlist.dev.txt"
        watchlist = []
        watchfile = open(self.getFile(watchlistPath, watchlistDevPath), 'r')
    
        for line in watchfile: 
            elem = line.split(",")
            if not line.strip() or line.startswith("#") or elem[1] == 0:
                continue
             
            for index, e in enumerate(elem): 
                if index == 3:
                    elem[index] = e.replace(" ", "", 1)
                else:
                    elem[index] = e.replace(" ", "")
                    
            d = self.parseDate(elem[0])
            url = normalizeString(elem[4])
            watchElement = {
                "Date" : d,
                "Episodes" : int(elem[1]),
                "Rank" : elem[2],
                "Name" : elem[3],
                "URL": url,
            }

            if not watchElement["Date"] > date.today():
                watchlist.append(watchElement)
            else:
                self.log.appendItemToStack("future_title", f"{watchElement["Name"]} {watchElement["Date"]}: {watchElement["URL"]}")

        useRank = self.getConfigValue("useRank")
        sorting = sorted(
            watchlist,
            key=lambda d: useRank.index(d["Rank"])
        )

        self.watchlist = sorting

    def getConfigValue(self, key): 
        config = self.config.get(key)

        if config is None: 
            self.log.appendItemToStack("general", f"{key} was used, but no config was found")

        return config

    def getWatchlistValue(self, item, key): 
        index = self.watchlist.index(item)
        return self.watchlist[index].get(key)
