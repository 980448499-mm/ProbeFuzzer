package org.example.corelearner;

/*
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */


import de.learnlib.acex.analyzers.AcexAnalyzers;
import de.learnlib.algorithms.ttt.mealy.TTTLearnerMealy;
import de.learnlib.api.algorithm.LearningAlgorithm;
import de.learnlib.api.logging.LearnLogger;
import de.learnlib.api.oracle.EquivalenceOracle;
import de.learnlib.api.query.DefaultQuery;
import de.learnlib.filter.statistic.Counter;
import de.learnlib.filter.statistic.oracle.MealyCounterOracle;
import de.learnlib.oracle.equivalence.MealyRandomWordsEQOracle;
import de.learnlib.oracle.equivalence.MealyWMethodEQOracle;
import de.learnlib.oracle.equivalence.MealyWpMethodEQOracle;
import de.learnlib.util.statistics.SimpleProfiler;
import de.learnlib.oracle.equivalence.CheckingEQOracle;
import net.automatalib.commons.util.collections.CollectionsUtil;
import net.automatalib.words.Word;
import net.automatalib.words.WordBuilder;
import net.automatalib.automata.transducers.MealyMachine;
import net.automatalib.serialization.dot.GraphDOT;
import net.automatalib.words.Word;
import net.automatalib.words.impl.SimpleAlphabet;
import org.example.corelearner.LogOracle.MealyLogOracle;
import org.example.corelearner.core.CoreConfig;
import org.example.corelearner.core.CoreSUL;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.logging.FileHandler;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.logging.SimpleFormatter;
import java.util.stream.Stream;


public class Learner {
    LearningConfig config;
    SimpleAlphabet<String> alphabet;
    StateLearnerSUL<String, String> sul;
    MealyLogOracle<String, String> logMemOracle;
    MealyCounterOracle<String, String> statsMemOracle;
    MealyCounterOracle<String, String> statsCachedMemOracle;
    LearningAlgorithm<MealyMachine<?, String, ?, String>, String, Word<String>> learningAlgorithm;

    MealyLogOracle<String, String> logEqOracle;
    MealyCounterOracle<String, String> statsEqOracle;
    MealyCounterOracle<String, String> statsCachedEqOracle;
    EquivalenceOracle<MealyMachine<?, String, ?, String>, String, Word<String>> equivalenceAlgorithm;
    EquivalenceOracle<MealyMachine<?, String, ?, String>, String, Word<String>> checkingCEAlgorithm;

    public List<List<String>> StoredCEs = new ArrayList<>();
    public List<Word<String>> WordCEs = new ArrayList<>();

    public Learner(LearningConfig config) throws Exception {
        this.config = config;
        loadCE();
        System.out.println("All CE loaded!");

        // Create output directory if it doesn't exist
        Path path = Paths.get(config.output_dir);
        if (Files.notExists(path)) {
            Files.createDirectories(path);
        }

        configureLogging(config.output_dir);

        LearnLogger log = LearnLogger.getLogger(Learner.class.getSimpleName());

        log.info("Using Core SUL");

        sul = new CoreSUL(new CoreConfig(config));
        alphabet = ((CoreSUL) sul).getAlphabet();

        loadLearningAlgorithm(config.learning_algorithm, alphabet, sul);
        loadEquivalenceAlgorithm(config.eqtest, alphabet, sul);

    }

    public void loadCE(){
        String file_name = "./CEStore/input";
        try (BufferedReader br = new BufferedReader(new FileReader(file_name))) {
            String line;
            while ((line = br.readLine()) != null) {
                if (line.contains("INFO")) {
                    line = line.split("/")[0].split("\\[")[1].replaceAll("\\|", " ");
                    //System.out.println(line);
                    List<String> split_line = Arrays.asList(line.split("\\s+"));
                    StoredCEs.add(split_line);
                    WordCEs.add(generateCEWord(split_line));
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public Word<String> generateCEWord(List<String> StoredCEs) {

        int length = StoredCEs.size();
        final WordBuilder<String> result = new WordBuilder<>(length);

        for (int j = 0; j < length; ++j) {
            String sym = StoredCEs.get(j);
            result.append(sym);
        }

        return (Word<String>) result.toWord();
    }

    public static void writeAutModel(MealyMachine<?, String, ?, String> model, SimpleAlphabet<String> alphabet, String filename) throws FileNotFoundException {
        // Make use of LearnLib's internal representation of states as integers
        @SuppressWarnings("unchecked")
        MealyMachine<Integer, String, ?, String> tmpModel = (MealyMachine<Integer, String, ?, String>) model;

        // Write output to aut-file
        File autFile = new File(filename);
        PrintStream psAutFile = new PrintStream(autFile);

        int nrStates = model.getStates().size();
        // Compute number of transitions, assuming the graph is complete
        int nrTransitions = nrStates * alphabet.size();

        psAutFile.println("des(" + model.getInitialState().toString() + "," + nrTransitions + "," + nrStates + ")");

        Collection<Integer> states = tmpModel.getStates();

        for (Integer state : states) {
            for (String input : alphabet) {
                String output = tmpModel.getOutput(state, input);
                Integer successor = tmpModel.getSuccessor(state, input);
                psAutFile.println("(" + state + ",'" + input + " / " + output + "', " + successor + ")");
            }
        }

        psAutFile.close();
    }

    public static void writeDotModel(MealyMachine<?, String, ?, String> model, SimpleAlphabet<String> alphabet, String filename) throws IOException, InterruptedException {
        // Write output to dot-file
        File dotFile = new File(filename);
        PrintStream psDotFile = new PrintStream(dotFile);
        GraphDOT.write(model, alphabet, psDotFile);
        psDotFile.close();

        // Convert .dot to .pdf
//        Runtime.getRuntime().exec("dot -Tpdf -O " + filename);
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Invalid number of parameters");
            System.exit(-1);
        }

        try {
            LearningConfig config = new LearningConfig(args[0]);

            System.out.println("Loaded Learning Config correctly");
            System.out.println(config.device);

            Learner learner = new Learner(config);
            learner.learn();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public void loadLearningAlgorithm(String algorithm, SimpleAlphabet<String> alphabet, StateLearnerSUL<String, String> sul) throws Exception {

        // Add a logging oracle
        logMemOracle = new MealyLogOracle<String, String>(sul, LearnLogger.getLogger("learning_queries"));


        // Count the number of queries actually sent to the SUL
        statsMemOracle = new MealyCounterOracle<String, String>(logMemOracle, "membership queries to SUL");


        // Use cache oracle to prevent double queries to the SUL
        // Count the number of queries to the cache
        statsCachedMemOracle = new MealyCounterOracle<String, String>(statsMemOracle, "membership queries to cache");

        if (algorithm.toLowerCase().equals("ttt")) {

            learningAlgorithm = new TTTLearnerMealy<String, String>(alphabet, statsCachedMemOracle, AcexAnalyzers.BINARY_SEARCH_BWD);
        } else {
            throw new Exception("Unknown learning algorithm " + config.learning_algorithm);
        }

    }

    public void loadEquivalenceAlgorithm(String algorithm, SimpleAlphabet<String> alphabet, StateLearnerSUL<String, String> sul) throws Exception {
        // Create the equivalence oracle
        // Add a logging oracle
        logEqOracle = new MealyLogOracle<String, String>(sul, LearnLogger.getLogger("equivalence_queries"));
        // Add an oracle that counts the number of queries
        statsEqOracle = new MealyCounterOracle<String, String>(logEqOracle, "equivalence queries to SUL");
        // Count the number of queries to the cache
        statsCachedEqOracle = new MealyCounterOracle<String, String>(statsEqOracle, "equivalence queries to cache");

        // Instantiate the selected equivalence algorithm
        switch (algorithm.toLowerCase()) {
            case "wmethod":
                equivalenceAlgorithm = new MealyWMethodEQOracle<String, String>(statsCachedEqOracle, config.max_depth);
                break;

            case "modifiedwmethod":
                equivalenceAlgorithm = new ModifiedWMethodEQOracle.MealyModifiedWMethodEQOracle<String, String>(config.max_depth, statsCachedEqOracle);
                break;

            case "wpmethod":
                equivalenceAlgorithm = new MealyWpMethodEQOracle<String, String>(statsCachedEqOracle, config.max_depth);
                checkingCEAlgorithm = new CheckingEQOracle<>(statsCachedEqOracle,1, WordCEs); //batch size is not useful here.
                System.out.println("checkingCEAlgorithm initialized!!!");
                break;

            case "randomwords":
                equivalenceAlgorithm = new MealyRandomWordsEQOracle<String, String>(statsCachedEqOracle,
                        config.min_length, config.max_length, config.nr_queries, new Random(config.seed));
                break;

            default:
                throw new Exception("Unknown equivalence algorithm " + config.eqtest);
        }
    }

    public void learn() throws IOException, InterruptedException {
        LearnLogger log = LearnLogger.getLogger(Learner.class.getSimpleName());

        log.info("Using learning algorithm " + learningAlgorithm.getClass().getSimpleName());
        log.info("Using equivalence algorithm " + equivalenceAlgorithm.getClass().getSimpleName());

        log.info("Starting learning");

        SimpleProfiler.start("Total time");

        boolean learning = true;
        Counter round = new Counter("Rounds", "");

        round.increment();
        log.logPhase("Starting round " + round.getCount());
        SimpleProfiler.start("Learning");
        learningAlgorithm.startLearning();
        SimpleProfiler.stop("Learning");

        MealyMachine<?, String, ?, String> hypothesis = learningAlgorithm.getHypothesisModel();
        while (learning) {
            // Write outputs
            writeDotModel(hypothesis, alphabet, config.output_dir + "/hypothesis_" + round.getCount() + ".dot");

            // Search counter-example
            SimpleProfiler.start("Searching for counter-example");
            DefaultQuery<String, Word<String>> counterExample = checkingCEAlgorithm.findCounterExample(hypothesis, alphabet); //open this line and comment out the next line, and also open "if(counterExample == null){" branch to enable CE feeding
//            DefaultQuery<String, Word<String>> counterExample = equivalenceAlgorithm.findCounterExample(hypothesis, alphabet);
            if (counterExample == null) { // used all CEs, check wp
                log.logPhase("used all CEs.");
                log.info(statsEqOracle.getStatisticalData().getSummary());
                counterExample = equivalenceAlgorithm.findCounterExample(hypothesis, alphabet);
            }
            SimpleProfiler.stop("Searching for counter-example");

            if (counterExample == null) {
                // No counter-example found, so done learning
                learning = false;

                // Write outputs
                writeDotModel(hypothesis, alphabet, config.output_dir + "/learnedModel.dot");
                //writeAutModel(hypothesis, alphabet, config.output_dir + "/learnedModel.aut");
            } else {
                // Counter example found, update hypothesis and continue learning
                log.logCounterexample("Counter-example found: " + counterExample);
                log.info(SimpleProfiler.getResults());
                log.info(round.getSummary());
                log.info(statsMemOracle.getStatisticalData().getSummary());
                log.info(statsEqOracle.getStatisticalData().getSummary());
                log.info("States in the hypothesis: " + hypothesis.size());

                round.increment();
                log.logPhase("Starting round " + round.getCount());

                SimpleProfiler.start("Learning");
                try {
                    learningAlgorithm.refineHypothesis(counterExample);
                } catch (Exception e) {
                    System.out.print(e.toString());
                    System.exit(1);
                }
                SimpleProfiler.stop("Learning");

                hypothesis = learningAlgorithm.getHypothesisModel();
            }
        }

        SimpleProfiler.stop("Total time");

        // Output statistics
        log.info("-------------------------------------------------------");
        log.info(SimpleProfiler.getResults());
        log.info(round.getSummary());
        log.info(statsMemOracle.getStatisticalData().getSummary());
        log.info(statsCachedMemOracle.getStatisticalData().getSummary());
        log.info(statsEqOracle.getStatisticalData().getSummary());
        log.info(statsCachedEqOracle.getStatisticalData().getSummary());
        log.info("States in final hypothesis: " + hypothesis.size());
    }

    public void configureLogging(String output_dir) throws SecurityException, IOException {

        Logger loggerLearnlib = Logger.getLogger("de.learnlib");
        loggerLearnlib.setLevel(Level.ALL);
        FileHandler fhLearnlibLog = new FileHandler(output_dir + "/learnlib.log");
        loggerLearnlib.addHandler(fhLearnlibLog);
        fhLearnlibLog.setFormatter(new SimpleFormatter());

        Logger loggerLearner = Logger.getLogger(Learner.class.getSimpleName());
        loggerLearner.setLevel(Level.ALL);
        FileHandler fhLearnerLog = new FileHandler(output_dir + "/learner.log");
        loggerLearner.addHandler(fhLearnerLog);
        fhLearnerLog.setFormatter(new SimpleFormatter());

        Logger loggerLearningQueries = Logger.getLogger("learning_queries");
        loggerLearningQueries.setLevel(Level.ALL);
        FileHandler fhLearningQueriesLog = new FileHandler(output_dir + "/learning_queries.log");
        loggerLearningQueries.addHandler(fhLearningQueriesLog);
        fhLearningQueriesLog.setFormatter(new SimpleFormatter());

        Logger loggerEquivalenceQueries = Logger.getLogger("equivalence_queries");
        loggerEquivalenceQueries.setLevel(Level.ALL);
        FileHandler fhEquivalenceQueriesLog = new FileHandler(output_dir + "/equivalence_queries.log");
        loggerEquivalenceQueries.addHandler(fhEquivalenceQueriesLog);
        fhEquivalenceQueriesLog.setFormatter(new SimpleFormatter());
        loggerEquivalenceQueries.warning("start logger\n");

    }
}

