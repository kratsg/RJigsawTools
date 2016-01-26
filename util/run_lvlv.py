import ROOT
# Workaround to fix threadlock issues with GUI
ROOT.PyConfig.StartGuiThread = False
import logging
logging.basicConfig(level=logging.INFO)
from optparse import OptionParser

import os
from datetime import date

parser = OptionParser()
parser.add_option("--submitDir", help   = "dir to store the output", default="submit_dir")
parser.add_option("--dataDir", help     = "dir to search for input"  , default="/afs/cern.ch/work/r/rsmith/lvlv_datasets/")

parser.add_option("--gridDS", help      = "gridDS"  , default="")
parser.add_option("--gridInputFile",help= "gridInputFile"  , default=""  )
parser.add_option("--gridUser", help    = "gridUser"  , default=os.environ.get("USER")  )
parser.add_option("--gridTag", help     = "gridTag", default=date.today().strftime("%m%d%y"))

parser.add_option("--driver", help      = "select where to run", choices=("direct", "prooflite", "LSF","grid"), default="direct")
parser.add_option('--doOverwrite', help = "Overwrite submit dir if it already exists",action="store_true", default=False)
parser.add_option('--nevents', help     = "Run n events ", default = -1 )
parser.add_option('--verbosity', help   = "Run all algs at the selected verbosity.",choices=("info", "warning","error", "debug", "verbose"), default="error")
#parser.add_option("--whichAnalysis", help="select analysis", choices=("noCut", "Zmumu" , "Zee", "Wenu","NONE"), default="NONE")
#parser.add_option("--errorLevel", help="select error level", choices=("VERBOSE","DEBUG","WARNING","ERROR"), default="WARNING")


(options, args) = parser.parse_args()

import atexit
@atexit.register
def quiet_exit():
    ROOT.gSystem.Exit(0)

def setVerbosity ( alg , levelString ) :
    level = None
    if levelString == "info"    : level = ROOT.MSG.INFO
    if levelString == "warning" : level = ROOT.MSG.WARNING
    if levelString == "error"   : level = ROOT.MSG.ERROR
    if levelString == "debug"   : level = ROOT.MSG.DEBUG
    if levelString == "verbose" : level = ROOT.MSG.VERBOSE

    if not level :
        logging.info("you set an illegal verbosity! Exiting.")
        quiet_exit()
    alg.setMsgLevel(level)

def setupST() :
    susyTools = ROOT.ST.SUSYObjDef_xAOD("getlist")
    #we need to ensure these settings are the same as those used by the CalibrateST alg
    susyTools.setProperty("METDoTrkSyst", True );
    susyTools.setProperty("METDoCaloSyst", False );

    logging.info("initializing SUSYTools")
    susyTools.initialize()
    return susyTools


ROOT.gROOT.Macro( '$ROOTCOREDIR/scripts/load_packages.C' )
# Initialize the xAOD infrastructure
#ROOT.xAOD.Init()

# create a new sample handler to describe the data files we use
logging.info("creating new sample handler")
sh_all = ROOT.SH.SampleHandler()

if (options.gridInputFile or options.gridDS) and (options.driver!="grid"):
    print ""
    print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    print "Are you sure you didn't mean to run this with --driver grid?"
    raw_input("Press Enter to continue... or ctrl-c if you effed up...")

if options.gridInputFile:
    with open(options.gridInputFile,'r') as f:
        for ds in f:
            # print "Adding %s to SH"%ds.rstrip()
            ROOT.SH.addGrid(sh_all, ds.rstrip() )
elif options.gridDS:
    ROOT.SH.scanDQ2(sh_all, options.gridDS);
else:
    mylist = ROOT.SH.DiskListLocal(options.dataDir)
    ROOT.SH.scanDir(sh_all,mylist, "*")


sh_all.setMetaString ("nc_tree", "CollectionTree");

sh_all.printContent();

# this is the basic description of our job
logging.info("creating new job")
job = ROOT.EL.Job()
job.sampleHandler(sh_all)
job.useXAOD()

logging.info("creating algorithms")

susyTools = setupST()

import collections
algsToRun = collections.OrderedDict()

outputFilename = "trees"
output = ROOT.EL.OutputStream(outputFilename);

#algsToRun["basicEventSelection"  ]       = ROOT.BasicEventSelection()
#algsToRun["basicEventSelection"  ].setConfig("$ROOTCOREBIN/data/RJigsawTools/baseEvent.config")
algsToRun["mcEventVeto"  ]               = ROOT.MCEventVeto()

#todo probably make this a function or something
for syst in susyTools.getSystInfoList() :
    algsToRun["calibrateST_" + syst.systset.name() ]               = ROOT.CalibrateST()
    algsToRun["calibrateST_" + syst.systset.name() ].systName      = syst.systset.name()

    algsToRun["preselectDileptonicWW_" + syst.systset.name() ]     = ROOT.PreselectDileptonicWWEvents()
    algsToRun["selectDileptonicWW_"    + syst.systset.name() ]     = ROOT.SelectDileptonicWWEvents()
    algsToRun["postselectDileptonicWW_" + syst.systset.name() ]    = ROOT.PostselectDileptonicWWEvents()

#todo move the enums to a separate file since they are shared by multiple algs
    algsToRun["calculateRJigsawVariables_" + syst.systset.name() ]                = ROOT.CalculateRJigsawVariables()
    algsToRun["calculateRJigsawVariables_" + syst.systset.name() ].calculatorName = ROOT.CalculateRJigsawVariables.lvlvCalculator
    algsToRun["calculateRegionVars_" + syst.systset.name() ]                      = ROOT.CalculateRegionVars()
    algsToRun["calculateRegionVars_" + syst.systset.name() ].calculatorName       = ROOT.CalculateRegionVars.lvlvCalculator

    for regionName in ["SR","CR1L","CR0L"]:
        tmpWriteOutputNtuple                     = ROOT.WriteOutputNtuple()
        tmpWriteOutputNtuple.outputName          = outputFilename
        tmpWriteOutputNtuple.regionName          = regionName
        tmpWriteOutputNtuple.systName            = syst.systset.name()
        algsToRun["writeOutputNtuple_"+regionName + syst.systset.name()] = tmpWriteOutputNtuple

job.outputAdd(output);

for name,alg in algsToRun.iteritems() :
    setVerbosity(alg , options.verbosity)
    logging.info("adding " + name + " to algs" )
    alg.SetName(name)#this is needed to see the alg names with athena messaging
    job.algsAdd(alg)

if options.nevents > 0 :
    logging.info("Running " + str(options.nevents) + " events")
    job.options().setDouble (ROOT.EL.Job.optMaxEvents, float(options.nevents));

import os
if os.path.isdir(options.submitDir) :
    print options.submitDir + " already exists."
    if options.doOverwrite :
        print "Overwriting previous submitDir"
        import shutil
        shutil.rmtree(options.submitDir)
    else :
        print "Exiting.  If you want to overwrite the previous submitDir, use --doOverwrite"
        quiet_exit()

logging.info("creating driver")
driver = None
if (options.driver == "direct"):
    print "direct driver"
    logging.info("running on direct")
    driver = ROOT.EL.DirectDriver()
    logging.info("submit job")
    driver.submit(job, options.submitDir)
elif (options.driver == "prooflite"):
    print "prooflite"
    logging.info("running on prooflite")
    driver = ROOT.EL.ProofDriver()
    logging.info("submit job")
    driver.submit(job, options.submitDir)
elif (options.driver == "grid"):
    print "grid driver"
    logging.info("running on Grid")
    driver = ROOT.EL.PrunDriver()
    driver.options().setString("nc_outputSampleName", "user.%s.%%in:name[2]%%.%%in:name[3]%%.%s"%(options.gridUser,options.gridTag)   );
    driver.options().setDouble(ROOT.EL.Job.optGridMergeOutput, 1);

    logging.info("submit job")
    driver.submitOnly(job, options.submitDir)


