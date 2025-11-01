from utils.source import LoadData

class Logger:
    def __init__(self):
        self.stack = {}

    def registerStack(self, stackName):
        self.stack.update({f"{stackName}": []})

    def appendItemToStack(self, stackName, item):
        self.stack[stackName].append(item)
        
    def printToConsole(self, debugOutput, printBool): 
        if printBool:
            for line in debugOutput:
                print(line)
    
    def printToFile(self, debugOutput, printBool, filename="debug.txt"):
        if printBool:
            with open(filename, "w", encoding="utf-8") as f:
                for line in debugOutput:
                    f.write(line + "\n")

    def normalizeString(self, config):
        return str(config).replace("\n", "").replace("\r", "").replace("\t", "").strip()
    
    def writeConfigToLogger(self, config):
        self.appendItemToStack("config", "Config:")
        self.appendItemToStack("config", f"showAll: {self.normalizeString(config["showAll"])}")
        self.appendItemToStack("config", f"showSimulcast: {self.normalizeString(config["showSimulcast"])}")
        if config["showSimulcast"]:
            self.appendItemToStack("config", f"showSimulcastAdditionalPast: {self.normalizeString(config["showSimulcastAdditionalPast"])}")
            if config["showSimulcastAdditionalPast"]:
                self.appendItemToStack("config", f"showSimulcastDaysPast: {self.normalizeString(config["showSimulcastDaysPast"])}")

            self.appendItemToStack("config", f"showSimulcastAdditionalFuture: {self.normalizeString(config["showSimulcastAdditionalFuture"])}")
            if config["showSimulcastAdditionalFuture"]:
                self.appendItemToStack("config", f"showSimulcastDaysFuture: {self.normalizeString(config["showSimulcastDaysFuture"])}")
        self.appendItemToStack("config", f"showWildcard: {self.normalizeString(config["showWildcard"])}")
        formats = config["dateFormats"].split(",")
        value = int(config["dateFormatUse"])-1
        self.appendItemToStack("config", f"dateFormatUse: {self.normalizeString(formats[value])}")
        self.appendItemToStack("config", f"printDebugToFile: {self.normalizeString(config["printDebugToFile"])}")
        self.appendItemToStack("config", f"printDebugToConsole: {self.normalizeString(config["printDebugToConsole"])}")
        self.appendItemToStack("config", f"printDebugConfig: {self.normalizeString(config["printDebugConfig"])}")
        self.appendItemToStack("config", f"printDebugGeneral: {self.normalizeString(config["printDebugGeneral"])}")
        self.appendItemToStack("config", f"printDebugFutureTitle: {self.normalizeString(config["printDebugFutureTitle"])}")
        self.appendItemToStack("config", f"printDebugShowAll: {self.normalizeString(config["printDebugShowAll"])}")
        self.appendItemToStack("config", f"printDebugShowSimulcast: {self.normalizeString(config["printDebugShowSimulcast"])}")
        self.appendItemToStack("config", f"printDebugShowSimulcastAdditional: {self.normalizeString(config["printDebugShowSimulcastAdditional"])}")
        self.appendItemToStack("config", f"printDebugShowWildcard: {self.normalizeString(config["printDebugShowWildcard"])}")

    def printLog(self, debugOutput, config):   
        self.printToConsole(debugOutput, config["printDebugToConsole"])
        self.printToFile(debugOutput, config["printDebugToFile"])

    def writeLogger(self, config):
        debugOutput = []
        for key in self.stack:
            if key == "config":
                if not config["printDebugConfig"]:
                    continue
            if key == "general":
                if not config["printDebugGeneral"]:
                    continue     
            if key == "future_title":
                if not config["printDebugFutureTitle"]:
                    continue     
            if key == "show_all":
                if not config["printDebugShowAll"]:
                    continue
            if key == "show_simulcast":
                if not config["printDebugShowSimulcast"]:
                    continue
            if key == "show_simulcast_past" or key == "show_simulcast_future":
                if not config["printDebugShowSimulcast"] or not config["printDebugShowSimulcastAdditional"]:
                    continue
            if key == "show_wildcard" or key == "skipped_wildcard":
                if not config["printDebugShowWildcard"]:
                    continue

            if len(self.stack[key]) > 1:
                for index, elem in enumerate(self.stack[key]): 
                    debugOutput.append(elem)
                debugOutput.append("\n")
        self.printLog(debugOutput, config)    
    
    def printLogging(self, config): 
        self.writeConfigToLogger(config)
        self.writeLogger(config)
