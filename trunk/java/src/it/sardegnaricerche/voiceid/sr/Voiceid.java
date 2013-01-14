package it.sardegnaricerche.voiceid.sr;

import it.sardegnaricerche.voiceid.db.Identifier;
import it.sardegnaricerche.voiceid.db.VoiceDB;
import it.sardegnaricerche.voiceid.db.gmm.GMMVoiceDB;
import it.sardegnaricerche.voiceid.db.gmm.UBMModel;
import it.sardegnaricerche.voiceid.fm.Diarizator;
import it.sardegnaricerche.voiceid.fm.LIUMStandardDiarizator;
import it.sardegnaricerche.voiceid.utils.DistanceStrategy;
import it.sardegnaricerche.voiceid.utils.Scores;
import it.sardegnaricerche.voiceid.utils.Strategy;
import it.sardegnaricerche.voiceid.utils.ThresholdStrategy;
import it.sardegnaricerche.voiceid.utils.Utils;
import it.sardegnaricerche.voiceid.utils.VLogging;
import it.sardegnaricerche.voiceid.utils.VoiceidException;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.logging.Logger;

import javax.sound.sampled.UnsupportedAudioFileException;


/**
 * VoiceID, Copyright (C) 2011-2013, Sardegna Ricerche. Email:
 * labcontdigit@sardegnaricerche.it, michela.fancello@crs4.it,
 * mauro.mereu@crs4.it Web: http://code.google.com/p/voiceid Authors: Michela
 * Fancello, Mauro Mereu
 * 
 * This program is free software: you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later
 * version.
 * 
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 * FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
 * details.
 * 
 * @author Michela Fancello, Mauro Mereu

 * 
 */

/**
 * Voiceid is a class that represents a whole file diarization and
 * identification workflow. More in deep, the Voiceid class is associated to a
 * VoiceDB, the voice model database instance that implements all the methods to
 * compare audio against models, an input file, which can be a Video or audio
 * file, and a DiarizationManager, which implements the diarization algorithms.
 * The Voiceid class gives some simple methods to extract speakers' information
 * from the audio.
 * 
 */
public class Voiceid {

	private static Logger logger = VLogging.getDefaultLogger();
	private ArrayList<VCluster> clusters;
	private VoiceDB voicedb;
	private File inputfile;
	private File wavPath;
	private Diarizator diarizationManager;

	/**
	 * The main {@link Voiceid} constructor, where you can specify which kind of
	 * {@link VoiceDB} and {@link Diarizator} to use.
	 * 
	 * 
	 * @param voicedb
	 *            a valid VoiceDB instance
	 * @param inputFile
	 *            the input file containing an audio track
	 * @param manager
	 *            a valid Diarizator
	 * @throws IOException
	 * @throws ClassNotFoundException
	 */
	public Voiceid(VoiceDB voicedb, File inputFile, Diarizator manager)
			throws IOException, ClassNotFoundException {
		clusters = null;
		this.voicedb = voicedb;
		this.inputfile = inputFile;
		this.diarizationManager = manager;
		this.verifyInputFile();
	}

	/**
	 * A custom constructor for {@link Voiceid} that has a {@link GMMVoiceDB}
	 * instantiated with dbDir, and the {@link LIUMStandardDiarizator}.
	 * 
	 * @param dbDir
	 *            the path where is your {@link VoiceDB}
	 * @param inpuFile
	 *            a {@link File} instance representing the input file
	 * @throws Exception
	 */
	public Voiceid(String dbDir, File inpuFile) throws Exception {
		this(new GMMVoiceDB(dbDir), inpuFile, new LIUMStandardDiarizator());
	}

	/**
	 * A custom constructor for {@link Voiceid} that has a {@link GMMVoiceDB}
	 * instantiated with dbDir, and the {@link LIUMStandardDiarizator}.
	 * 
	 * @param dbDir
	 *            the path where is your {@link VoiceDB}.
	 * @param inputPath
	 *            the input file path
	 * @throws Exception
	 */
	public Voiceid(String dbDir, String inputPath) throws Exception {
		this(dbDir, new File(inputPath));
	}

	/**
	 * An utility to check if the file in input is a regular file.
	 * 
	 * @throws IOException
	 */
	private void verifyInputFile() throws IOException {
		if (!this.inputfile.isFile())
			throw new IOException(this.inputfile + " not a regular file");
	}

	/**
	 * Run the diarization process and generate the clusters (speakers)
	 * representations. Split the original audio file according to the
	 * identified clusters.
	 * 
	 * @throws VoiceidException
	 * @throws IOException
	 */
	public void extractClusters() throws VoiceidException, IOException {
		try {
			if (!Utils.isGoodWave(this.inputfile)) {
				logger.info("Ok, let's transcode this wav"); // TODO: rename to
																// another wav e
																// resample
				throw new VoiceidException(
						"Transcoding of bad(format) wav files still not implemented!");
			}
			this.wavPath = new File(Utils.getBasename(this.inputfile) + ".wav");
		} catch (UnsupportedAudioFileException e) {
			logger.severe(e.getMessage());
			this.toWav();
		} catch (IOException e) {
			logger.severe(e.getMessage());
		}
		clusters = diarizationManager.extractClusters(inputfile);
		this.trimClusters();
	}

	/**
	 * Serch the {@link VoiceDB} to assign a known voice to the identified
	 * clusters.
	 * 
	 * @return
	 * @throws Exception
	 */
	public boolean matchClusters() throws Exception {
		Strategy[] stratArr = { new ThresholdStrategy(-33.0),
				new DistanceStrategy(0.01) };
		for (VCluster c : this.clusters) {
			Scores tmp = voicedb.voiceLookup(c.getSample(), c.getGender());
			if (tmp != null) {
				logger.info("For cluster " + c.getLabel() + " best speaker is "
						+ tmp.getBest(stratArr).keySet());
				try {
					c.setIdentifier((Identifier) tmp.getBest(stratArr).keySet()
							.toArray()[0]);
				} catch (Exception ex) {
					c.setIdentifier(new Identifier("unknown"));
				}
			}
		}
		return true;
	}

	/**
	 * Split the original audio file according to the identified clusters.
	 * 
	 * @throws IOException
	 */
	private void trimClusters() throws IOException {
		for (VCluster c : this.clusters) {
			c.trimSegments(this.wavPath);
		}
	}

	/**
	 * Print a string representation of the clusters identified.
	 * 
	 * @throws IOException
	 */
	private void printClusters() throws IOException {
		for (VCluster c : this.clusters) {
			logger.info(c.getLabel() + ":" + c.getIdentifier());
		}
	}

	/**
	 * Convert to wav the inputFile to be processed by diarizator.
	 * 
	 * @throws IOException
	 */
	private void toWav() throws IOException {
		logger.fine("Gstreamer initialized");
		String filename = inputfile.getAbsolutePath();
		String name = Utils.getBasename(inputfile);
		String line[] = {
				"/bin/sh",
				"-c",
				"gst-launch filesrc location='"
						+ filename
						+ "' ! decodebin ! audioresample ! 'audio/x-raw-int,rate=16000' ! audioconvert !"
						+ " 'audio/x-raw-int,rate=16000,depth=16,signed=true,channels=1' ! wavenc ! filesink location="
						+ name + ".wav " };
		// TODO: fix for other OS' vvvvvvvvvv
		// logger.info(System.getProperty("os.name").toLowerCase());
		logger.fine(line[2]);
		try {
			Process p = Runtime.getRuntime().exec(line);
			p.waitFor();
			logger.fine(p.exitValue() + "");
		} catch (Exception err) {
			logger.severe(err.getMessage());
		}
		// Pipeline pipe = Pipeline.launch(line[2]);
		// pipe.play();
		// logger.info(pipe.getState().toString());
		this.wavPath = new File(name + ".wav");
	}

	public static void main(String[] args) {
		logger.info("Voiceid main method");
		logger.info("First argument: '" + args[0] + "'");
		long startTime = System.currentTimeMillis();
		try {
			GMMVoiceDB db = new GMMVoiceDB(args[0], new UBMModel(
					"/usr/local/share/voiceid/ubm.gmm" + ""));
			Voiceid voiceid = new Voiceid(db, new File(args[1]),
					new LIUMStandardDiarizator());
			// voiceid.toWav();
			voiceid.extractClusters();
			voiceid.matchClusters();
			voiceid.printClusters();
		} catch (IOException e) {
			logger.severe(e.getMessage());
		} catch (Exception ex) {
			logger.severe(ex.getMessage());
		}
		long endTime = System.currentTimeMillis();
		long duration = endTime - startTime;
		logger.info("Exit (" + ((float) duration / 1000) + " s)");
	}
}