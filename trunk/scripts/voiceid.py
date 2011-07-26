#!/usr/bin/env python 
from optparse import OptionParser
from multiprocessing import Process, cpu_count, active_children
import os
import shlex, subprocess
import sys, signal
import time
import re
import string
import shutil

lium_jar = os.path.expanduser('~/.voiceid/lib/LIUM_SpkDiarization-4.7.jar')
ubm_path  = os.path.expanduser('~/.voiceid/lib/ubm.gmm')
db_dir = os.path.expanduser('~/.voiceid/gmm_db')

verbose = False
keep_intermediate_files = False


dev_null = open('/dev/null','w')
if verbose:
	dev_null = None



class Cluster:
	""" A Cluster object, representing a computed cluster for a single speaker, with gender, a number of frames and environment """
	def __init__(self, name, gender, frames ):
		self.gender = gender
		self.frames = frames
		self.e = None
		self.name = name
		self.speaker = None
		self.speakers = {}
		self.wave = None
		self.mfcc = None
		self.segments = []
		self.seg_header = None
	def add_speaker(self, name, value):
		if self.speakers.has_key( name ) == False:
			self.speakers[ name ] = float(value)
		else:	
			if self.speakers[ name ] < float(value):
				self.speakers[ name ] = float(value)
	
	def get_mean(self):
		return sum(self.speakers.values()) / len(self.speakers) 
		
	def get_name(self):
		return self.name
	
	def get_best_speaker(self):
		max_val = -33.0		
		self.value = max(self.speakers.values())
		self.speaker = 'unknown'
		if self.value > max_val:
			for s in self.speakers:
				if self.speakers[s] == self.value:
					self.speaker = s
					break
		if self.get_distance() < .1:
			self.speaker = 'unknown'
		return self.speaker
		
	def get_distance(self):
		values = self.speakers.values()
		values.sort(reverse=True)
		return abs(values[1]) - abs(values[0])
		
	def get_m_distance(self):
		value = max(self.speakers.values())
		return abs( abs( value ) - abs( self.get_mean() ) )

	def generate_seg_file(self, filename):
		f = open(filename,'w')
		f.write(self.seg_header)
		start_time = 0
		for line in self.segments:
			line[2]=start_time
			start_time+=int(line[3])
			f.write("%s %s %s %s %s %s %s %s\n" % tuple(line) )
		f.close()

	def build_and_store_gmm(self, show):
		oldshow = self.wave[:-4]
		
		shutil.copy(oldshow+'.wav', show+'.wav')
		shutil.copy(oldshow+'.mfcc', show+'.mfcc')
		shutil.copy(oldshow+'.seg', show+'.seg')

		ident_seg(show, self.speaker)

		train_init(show)

		train_map(show)
	    	ensure_file_exists(show+".gmm")
		shutil.move(show+'.gmm', os.path.join(db_dir,self.gender) )
		

		
def start_subprocess(commandline):
	""" Starts a subprocess using the given commandline and check for correct termination """
	args = shlex.split(commandline)
	p = subprocess.Popen(args, stdin=dev_null,stdout=dev_null, stderr=dev_null)
	retval = p.wait()
	if retval != 0: 
		raise Exception("Subprocess %s closed unexpectedly [%s]" %  (str(p), commandline) )

def ensure_file_exists(filename):
	""" Ensure file exists and is not empty, otherwise raise an Exception """
	if not os.path.exists(filename):
		raise Exception("File %s not correctly created"  % filename)
	if not (os.path.getsize(filename) > 0):
		raise Exception("File %s empty"  % filename)

def  check_deps():
	""" Check for dependency """
        ensure_file_exists(lium_jar)

        dir_m = os.path.join(db_dir,"M")
        dir_f = os.path.join(db_dir,"F")
        dir_u = os.path.join(db_dir,"U")
        ensure_file_exists(ubm_path)
        if not os.path.exists(db_dir):
                raise Exception("No gmm db directory found in %s (take a look to the configuration, db_dir parameter)" % db_dir )
        if os.listdir(db_dir) == []:
                print "WARNING: Gmm db directory found in %s is empty" % db_dir
#               raise Exception("Gmm db directory found in %s is empty" % db_dir )
        if not os.path.exists(dir_m):
                os.makedirs(dir_m)
        if not os.path.exists(dir_f):
                os.makedirs(dir_f)
        if not os.path.exists(dir_u):
                os.makedirs(dir_u)


def humanize_time(secs):
	""" Convert seconds into time format """
	mins, secs = divmod(secs, 60)
	hours, mins = divmod(mins, 60)
	return '%02d:%02d:%02d,%s' % (hours, mins, int(secs), str(("%0.3f" % secs ))[-3:] )

def video2wav(show):
	""" Takes any kind of video or audio and convert it to a "RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit, mono 16000 Hz" wave file using gstreamer. If you call it passing a wave it checks if in good format, otherwise it converts the wave in the good format """
	def is_bad_wave(show):
		""" Check if the wave is in correct format for LIUM required input file """
		import wave
		par = None
		try:
			w = wave.open(show)
			par = w.getparams()
			w.close()
		except Exception,e:
			print e
			return True
		if par[:3] == (1,2,16000) and par[-1:] == ('not compressed',):
			return False
		else:
			return True

	name, ext = os.path.splitext(show)
	if ext != '.wav' or is_bad_wave(show):
		start_subprocess( "gst-launch filesrc location='"+show+"' ! decodebin ! audioresample ! 'audio/x-raw-int,rate=16000' ! audioconvert ! 'audio/x-raw-int,rate=16000,depth=16,signed=true,channels=1' ! wavenc ! filesink location="+name+".wav " )
	ensure_file_exists(name+'.wav')


def diarization(showname):
	""" Takes a wave file in the correct format and build a segmentation file. The seg file shows how much speakers are in the audio and when they talk """
	start_subprocess( 'java -Xmx2024m -jar '+lium_jar+' --fInputMask=%s.wav --sOutputMask=%s.seg --doCEClustering ' +  showname )
	ensure_file_exists(showname+'.seg')

def seg2trim(segfile):
	""" Take a wave and splits it in small waves in this directory structure <file base name>/<cluster>/<cluster>_<start time>.wav """
	basename, extension = os.path.splitext(segfile)
	s = open(segfile,'r')
	for line in s.readlines():
		if not line.startswith(";;"):
			arr = line.split()
			clust = arr[7]
			st = float(arr[2])/100
			end = float(arr[3])/100
			try:
				mydir = os.path.join(basename, clust)
				os.makedirs( mydir )
			except os.error as e:
				if e.errno == 17:
					pass
				else:
					raise os.error
			wave_path = os.path.join( basename, clust, "%s_%s.wav" % (clust, st) )
			commandline = "sox %s.wav %s trim  %s %s" % ( basename, wave_path, st, end )
			start_subprocess(commandline)
			ensure_file_exists( wave_path )
	s.close()

def seg2srt(segfile):
	""" Takes a seg file and convert it in a subtitle file (srt) """
	def readtime(aline):
		return int(aline[2])

	basename, extension = os.path.splitext(segfile)	
	s = open(segfile,'r')
	lines = []
	for line in s.readlines():
		if not line.startswith(";;"):
			arr=line.split()
			lines.append(arr)
	s.close()
	
	lines.sort(key=readtime, reverse=False)
	fileoutput = basename+".srt"
	srtfile = open(fileoutput,"w")
	row = 0
	for line in lines:
		row = row +1
		st = float(line[2])/100
		en = st+float(line[3])/100
		srtfile.write(str(row)+"\n")
		srtfile.write(humanize_time(st) + " --> " + humanize_time(en) +"\n")               
		srtfile.write(line[7]+"\n")
		srtfile.write(""+"\n")
			
	srtfile.close()
	ensure_file_exists(basename+'.srt')

def video2trim(videofile):
	""" Takes a video or audio file and converts it into smaller waves according to the diarization process """
	print "*** converting video to wav ***"
	video2wav(videofile)
	show, ext = os.path.splitext(videofile)
	print "*** diarization ***"
	diarization(show)
	print "*** trim ***"
	seg2trim(show+'.seg')

def extract_mfcc(show):
	""" Extract audio features from the wave file, in particular the mel-frequency cepstrum using a sphinx tool """
	commandline = "sphinx_fe -verbose no -mswav yes -i %s.wav -o %s.mfcc" %  ( show, show )
	start_subprocess(commandline)
	ensure_file_exists(show+'.mfcc')

def ident_seg(showname,name):
	""" Takes a seg file and substitute the clusters with a given name or identifier """
	f = open(showname+'.seg','r')
	clusters=[]
	lines = f.readlines()
	for line in lines:
		for k in line.split():
			if k.startswith('cluster:'):
				prefix,c = k.split(':')
				clusters.append(c)
	f.close()
	output = open(showname+'.ident.seg', 'w')
	clusters.reverse()
	for line in lines:
		for c in clusters:
			line = line.replace(c,name)
		output.write(line+'\n')
	output.close()
	ensure_file_exists(showname+'.ident.seg')

def train_init(show):
	""" Train the initial speaker gmm model """
	commandline = 'java -Xmx256m -cp '+lium_jar+' fr.lium.spkDiarization.programs.MTrainInit --help --sInputMask=%s.ident.seg --fInputMask=%s.wav --fInputDesc="audio16kHz2sphinx,1:3:2:0:0:0,13,1:1:300:4"  --emInitMethod=copy --tInputMask='+ubm_path+' --tOutputMask=%s.init.gmm '+show
	start_subprocess(commandline)
	ensure_file_exists(show+'.init.gmm')

def train_map(show):
	""" Train the speaker model using a MAP adaptation method """
	commandline = 'java -Xmx256m -cp '+lium_jar+' fr.lium.spkDiarization.programs.MTrainMAP --help --sInputMask=%s.ident.seg --fInputMask=%s.mfcc --fInputDesc="audio16kHz2sphinx,1:3:2:0:0:0,13,1:1:300:4"  --tInputMask=%s.init.gmm --emCtrl=1,5,0.01 --varCtrl=0.01,10.0 --tOutputMask=%s.gmm ' + show 
	start_subprocess(commandline)
	ensure_file_exists(show+'.gmm')

def srt2subnames(showname, key_value):
	""" Substitute cluster names with real names in subtitles """

	def replace_words(text, word_dic):
	    """
	    take a text and replace words that match a key in a dictionary with
	    the associated value, return the changed text
	    """
	    rc = re.compile('|'.join(map(re.escape, word_dic)))
		
	    def translate(match):
		return word_dic[match.group(0)]+'\n'
	    
	    return rc.sub(translate, text)

	file_original_subtitle = open(showname+".srt")
	original_subtitle = file_original_subtitle.read()
	file_original_subtitle.close()
	key_value=dict(map(lambda (key, value): (str(key)+"\n", value), key_value.items()))
	text = replace_words(original_subtitle, key_value)
	out_file = showname+".ident.srt"
	# create a output file
	fout = open(out_file, "w")
	fout.write(text)
	fout.close()	
	ensure_file_exists(out_file)

def extract_clusters(filename, clusters):
	""" Read clusters from segmentation file """
	f = open(filename,"r")
	last_cluster = None
	for l in f:
		 if l.startswith(";;") :
			speaker_id = l.split()[1].split(':')[1]	
			clusters[ speaker_id ] = Cluster(name=speaker_id, gender='U', frames=0)
			last_cluster = clusters[ speaker_id ]
			last_cluster.seg_header = l
		 else:
			line = l.split()
			last_cluster.segments.append(line)
			last_cluster.frames += int(line[3])
			last_cluster.gender =  line[4]
			last_cluster.e =  line[5]
	f.close()

def mfcc_vs_gmm(showname, gmm, gender):
	""" Match a mfcc file and a given gmm model file """
	commandline = 'java -Xmx256M -Xms256M -cp '+lium_jar+'  fr.lium.spkDiarization.programs.MScore --sInputMask=%s.seg   --fInputMask=%s.mfcc  --sOutputMask=%s.ident.'+gender+'.'+gmm+'.seg --sOutputFormat=seg,UTF8  --fInputDesc="audio16kHz2sphinx,1:3:2:0:0:0,13,1:0:300:4" --tInputMask='+db_dir+'/'+gender+'/'+gmm+' --sTop=8,'+ubm_path+'  --sSetLabel=add --sByCluster '+  showname 
	start_subprocess(commandline)
	ensure_file_exists(showname+'.ident.'+gender+'.'+gmm+'.seg')


def manage_ident(showname, gmm, clusters):
	""" Takes all the files created by the call of mfcc_vs_gmm() on the whole speakers db and put all the results in a bidimensional dictionary """
	f = open("%s.ident.%s.seg" % (showname,gmm ) ,"r")
	for l in f:
		 if l.startswith(";;"):
			cluster, speaker = l.split()[ 1 ].split(':')[ 1 ].split('_')
			i = l.index('score:'+speaker) + len('score:'+speaker+" = ")
			ii = l.index(']',i) -1
			value = l[i:ii]
			clusters[ cluster ].add_speaker( speaker, value )
			"""
			if clusters[ cluster ].has_key( speaker ) == False:
				clusters[ cluster ][ speaker ] = float(value)
			else:
				if clusters[ cluster ][ speaker ] < float(value):
					clusters[ cluster ][ speaker ] = float(value)
			"""
	f.close()
	if not keep_intermediate_files:
		os.remove("%s.ident.%s.seg" % (showname,gmm ) )

def wave_duration(wavfile):
	""" Extract the duration of a wave file in sec """
	import wave
	w = wave.open(wavfile)
	par = w.getparams()
	w.close()
	return par[3]/par[2]

def merge_waves(input_waves,wavename):
	""" Takes a list of waves and append them all to a brend new destination wave """
	#if os.path.exists(wavename):
		#raise Exception("File gmm %s already exist!" % wavename)
	waves = [w.replace(" ","\ ") for w in input_waves]
	w = " ".join(waves)
	commandline = "sox "+str(w)+" "+ str(wavename)
	start_subprocess(commandline)
	
def build_gmm(show,name):
	""" Build a gmm (Gaussian Mixture Model) file from a given wave with a speaker identifier (name)  associated """
	
	diarization(show)
	
	ident_seg(show,name)
	
	extract_mfcc(show)
	
	train_init(show)
	
	train_map(show)
	


def extract_speakers(file_input,interactive):
	""" Takes a file input and identifies the speakers in it according to a speakers database. 
        If a speaker doesn't match any speaker in the database then sets it as unknown """
	cpus = cpu_count()
	clusters = {}
	start_time = time.time()
	video2trim( file_input )
	diarization_time =  time.time() - start_time
	basename, extension = os.path.splitext( file_input )
	seg2srt(basename+'.seg')
	extract_mfcc( basename )
	
	print "*** voice matching ***"
	extract_clusters( "%s.seg" %  basename, clusters )
	
	print "*** build 1 wave 4 cluster ***"
	for cluster in clusters:
		name = cluster
		videocluster =  os.path.join(basename,name)
		listwaves = os.listdir(videocluster)
		listw=[os.path.join(videocluster, f) for f in listwaves]
		#w = " ".join(listw)
		show = os.path.join(basename,name)
		clusters[cluster].wave = os.path.join(basename,name+".wav")
		merge_waves(listw,clusters[cluster].wave)
		extract_mfcc(show)
		clusters[cluster].generate_seg_file(show+".seg")
		
	"""Wave,seg(prendendo le info dal seg originale) e mfcc per ogni cluster"""
	"""Dal seg prendo il genere"""
	"""for mfcc for db_genere"""
	
	print "*** MScore ***"
	p = {}
	files_in_db = {}
	files_in_db["M"] = [ f for f in os.listdir(os.path.join(db_dir,"M")) if f.endswith('.gmm') ]
	files_in_db["F"] = [ f for f in os.listdir(os.path.join(db_dir,"F")) if f.endswith('.gmm') ]
	files_in_db["U"] = [ f for f in os.listdir(os.path.join(db_dir,"U")) if f.endswith('.gmm') ]
	for cluster in clusters:
		files = files_in_db[clusters[cluster].gender]
		showname = os.path.join(basename,cluster)
		for f in files:
			
			if  len(active_children()) < cpus :
				p[f+cluster] = Process(target=mfcc_vs_gmm, args=( showname, f, clusters[cluster].gender) )
				p[f+cluster].start()
			else:
				while len(active_children()) >= cpus:
					time.sleep(1)	
				p[f+cluster] = Process(target=mfcc_vs_gmm, args=( showname, f, clusters[cluster].gender ) )
				p[f+cluster].start()
	for proc in p:
		if p[proc].is_alive():
			p[proc].join()	
	
	for cluster in clusters:
		files = files_in_db[clusters[cluster].gender]
		showname = os.path.join(basename,cluster)
		for f in files:
			manage_ident( showname,clusters[cluster].gender+"."+f , clusters)
		
	print ""
	speakers = {}
	for c in clusters:
	    print c
            speakers[c] = clusters[c].get_best_speaker()
	    gender = clusters[c].gender
	    for speaker in clusters[c].speakers:
		print "\t %s %s" % (speaker , clusters[ c ].speakers[ speaker ])
	    print '\t ------------------------'
	    try:
		    distance = clusters[ c ].get_distance()
	    except:
	            distance = 1000.0
	    try:
		    mean = clusters[ c ].get_mean()
		    m_distance = clusters[ c ].get_m_distance()
	    except:
		    mean = 0
		    m_distance = 0
			
		    
	    proc = {}
	    if interactive == True and speakers[c] == "unknown":
	    	    name_i = interactive_training(basename,c)
		    best = name_i
		    speakers[c] = best
		    clusters[c].speaker = best
		    if speakers[c] != "unknown":
		    	    videocluster = os.path.join(basename,c)
		    	    listwaves = os.listdir(videocluster)
		    	    listw=[os.path.join(videocluster, f) for f in listwaves]
		    	    folder_db_dir = os.path.join(db_dir,gender)
		    	    
		    	    cont = 0
		    	    gmm_name = speakers[c]+".gmm"
		    	    if os.path.exists( os.path.join(folder_db_dir,gmm_name)):
		    	    	    while True:
		    	    	    	    cont = cont +1
		    	    	    	    gmm_name = speakers[c]+""+str(cont)+".gmm"
		    	    	    	    wav_name = speakers[c]+""+str(cont)+".wav"
		    	    	    	    if not os.path.exists( os.path.join(folder_db_dir,gmm_name)) and not os.path.exists( wav_name ):
		    	    	    	    	    break
		    	    
		    	    basename_gmm, extension_gmm = os.path.splitext(gmm_name)
		    	    
		    	    show=basename_gmm+".wav"       
		    	    
		    	    merge_waves(listw,show)
		    	    print "name speaker %s " % speakers[c]

			    def build_gmm_wrapper(basename_gmm,cluster):
				    clusters[cluster].build_and_store_gmm(basename_gmm)
				    
				    if not keep_intermediate_files:
					    os.remove("%s.wav" % basename_gmm )
					    os.remove("%s.seg" % basename_gmm )
					    os.remove("%s.mfcc" % basename_gmm )
					    os.remove("%s.ident.seg" % basename_gmm )
					    os.remove("%s.init.gmm" % basename_gmm )
				    
				    
			    proc[c] = Process( target=build_gmm_wrapper, args=(basename_gmm,c) )
			    proc[c].start()
				    
		    
	    print '\t best speaker: %s (distance from 2nd %f - mean %f - distance from mean %f ) ' % (speakers[c] , distance, mean, m_distance)
        srt2subnames(basename, speakers)
	sec = wave_duration(basename+'.wav')
	total_time = time.time() - start_time
	if interactive:		
		print "Waiting for working processes"
		for p in proc:
			if proc[p].is_alive(): 
				proc[p].join()
	
	print "\nwav duration: %s\nall done in %dsec (%s) (diarization %dsec time:%s )  with %s cpus and %d voices in db (%f)  " % ( humanize_time(sec), total_time, humanize_time(total_time), diarization_time, humanize_time(diarization_time), cpus, len(files_in_db), float(total_time - diarization_time )/len(files_in_db) )

def interactive_training(videoname,cluster):
	""" A user interactive way to set the name to an unrecognized voice of a given cluster """
	print """Menu
	1) Listen
	2) Skip
	\n"""
	
	while True:
		char = raw_input("Choice: ")
		if char == "1":
			videocluster = str(videoname+"/"+cluster)
			listwaves = os.listdir(videocluster)
			listw=[os.path.join(videocluster, f) for f in listwaves]
			w = " ".join(listw)
			commandline = "play "+str(w)
			print "Listen %s :" % cluster
			args = shlex.split(commandline)
			p = subprocess.Popen(args, stdin=dev_null, stdout=dev_null, stderr=dev_null)
			
			
			while True:
				name = raw_input("Type speaker name or leave blank for unknown speaker: ")
		
				while True:
					if len(name) == 0:
						name = "unknown"
					ok = raw_input("Save as '"+name+"'? [y/n/r] ")
					if ok in ('y', 'ye', 'yes'):
						p.kill()
						return name
					if ok in ('n', 'no', 'nop', 'nope'):
					        break
					if ok in ('r',"replay"):
						if p.poll() == None:
							p.kill()
						p = subprocess.Popen(args, stdin=dev_null, stdout=dev_null, stderr=dev_null)
						break
					print "Yes or no, please!"

			p.kill()
			break
		if char == "2":
			return "unknown"
			
			
def remove_blanks_callback(option, opt_str, value, parser):
	"""Remove all white spaces in filename and substitute with underscores"""
	if len(parser.rargs) == 0:
		parser.error("incorrect number of arguments")
	file_input=str(parser.rargs[0])
	new_file_input = file_input
	new_file_input=new_file_input.replace("'",'_').replace('-','_').replace(' ','_')
	os.rename(file_input,new_file_input)
	ensure_file_exists(new_file_input)
	file_input=new_file_input
	if getattr(parser.values, option.dest):
                args.extend(getattr(parser.values, option.dest))
	setattr(parser.values, option.dest, file_input)           

def multiargs_callback(option, opt_str, value, parser):
	"""Create an array from multiple args"""
	if len(parser.rargs) == 0:
		parser.error("incorrect number of arguments")
        args=[]
        for arg in parser.rargs:
                if arg[0] != "-":
                        args.append(arg)
                else:
                        del parser.rargs[:len(args)]
                        break
        if getattr(parser.values, option.dest):
                args.extend(getattr(parser.values, option.dest))
        setattr(parser.values, option.dest, args)

if __name__ == '__main__':
	usage = """%prog ARGS

examples:
    speaker identification
        %prog [ -d GMM_DB ] [ -j JAR_PATH ] -i INPUT_FILE

    speaker model creation
        %prog [ -d GMM_DB ] [ -j JAR_PATH ] -s SPEAKER_ID -g INPUT_FILE
        %prog [ -d GMM_DB ] [ -j JAR_PATH ] -s SPEAKER_ID -g WAVE WAVE ... WAVE  MERGED_WAVES """

	parser = OptionParser(usage)
	parser.add_option("-v", "--verbose", dest="verbose", action="store_true", default=False, help="verbose mode")
	parser.add_option("-i", "--identify", action="callback",callback=remove_blanks_callback, metavar="FILE", help="identify speakers in video or audio file", dest="file_input")
	parser.add_option("-g", "--gmm", action="callback", callback=multiargs_callback, dest="waves_for_gmm", help="build speaker model ")
	parser.add_option("-s", "--speaker", dest="speakerid", help="speaker identifier for model building")
	parser.add_option("-d", "--db",type="string", dest="dir_gmm", metavar="PATH",help="set the speakers models db path")
	parser.add_option("-j", "--jar",type="string", dest="jar", metavar="PATH",help="set the LIUM_SpkDiarization jar path")
	parser.add_option("-u", "--user-interactive", dest="interactive", action="store_true", help="User interactive training")
	parser.add_option("-k", "--keep-intermediatefiles", dest="keep_intermediate_files", action="store_true", help="keep all the intermediate files")
	
	(options, args) = parser.parse_args()

	if options.dir_gmm:
		db_dir = options.dir_gmm
	if options.jar:
		lium_jar = options.jar	
	check_deps()
	if options.file_input:
		extract_speakers(options.file_input,options.interactive)
		exit(0)
	if options.waves_for_gmm and options.speakerid:
		show = None
		waves = options.waves_for_gmm
		speaker = options.speakerid
		w=None
		if len(waves)>1:
			merge_waves(waves[:-1],waves[-1])
			w=waves[-1]
		else:
			w= waves[0]
		basename, extension = os.path.splitext(w)
		show=basename
		build_gmm(show,speaker)
		exit(0)
		
	parser.print_help()

