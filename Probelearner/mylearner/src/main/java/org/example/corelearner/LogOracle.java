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


import de.learnlib.api.logging.LearnLogger;
import de.learnlib.api.oracle.MembershipOracle.MealyMembershipOracle;
import de.learnlib.api.query.Query;
import net.automatalib.words.Word;
import net.automatalib.words.WordBuilder;
import org.example.corelearner.core.CoreSUL;
import org.example.corelearner.db.Cache;

import javax.annotation.ParametersAreNonnullByDefault;
import java.io.*;
import java.util.*;
import java.util.stream.Collectors;

import static java.lang.Thread.sleep;

// Based on SULOracle from LearnLib by Falk Howar and Malte Isberner
@ParametersAreNonnullByDefault
public class LogOracle<I, D> implements MealyMembershipOracle<I, D> {

    LearnLogger logger;
    StateLearnerSUL<I, D> sul;
    LearningConfig config = null;
    LearningResumer learning_resumer = null;
    Cache cache = null;

    public LogOracle(StateLearnerSUL<I, D> sul, LearnLogger logger) {
        try {
            this.sul = sul;
            this.logger = logger;
            logger.info("set logger " + logger.getName());
            File f1 = new File("inconsistent.log");
            if (f1.createNewFile()) {
                System.out.println("Inconsistent.log file has been created.");
            } else {
                PrintWriter writer1 = new PrintWriter(f1);
                writer1.print("");
                writer1.close();
            }
            try {
                this.config = new LearningConfig("core.properties");
            } catch (IOException e) {
                e.printStackTrace();
            }

            if (config.resume_learning_active) {

                System.out.println("Loading Learning Resumer");
                learning_resumer = new LearningResumer(config.path_to_resuming_log);
            }

            if (config.cache_active) {
                System.out.println("Initializing Cache");
                cache = new Cache(config.path_to_cache_log);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }

    }

    public Word<D> answerQuerySteps(Word<I> prefix, Word<I> suffix) {
        System.out.println("Query processing: ");
        System.out.println("[" + prefix + " | " + suffix + "]");

        List<Word<D>> responseWordList = new ArrayList<>();
        List<Word<D>> prefixToStringList = new ArrayList<>();
        List<String> responseToStringList = new ArrayList<>();
        int prefLen = prefix.length();
        if (prefix.toString().contains("ε")) {
            prefLen += 1;
        }
        Boolean resumed = false;
        int num_of_repeated_queries = 2;

        // Attempt to look up in resume learner prior to executing the query
        if (config.resume_learning_active) {
            // Prepares the Prefix and Suffix to look up in the map, mapping queries and corresponding result
            WordBuilder<D> wbPrefix = new WordBuilder<>(prefix.length());
            WordBuilder<D> wbSuffix = new WordBuilder<>(suffix.length());

            String query = prefix + "|" + suffix;
            //System.out.println("QUERY: " + query);
            String response = learning_resumer.query_resumer(query, prefLen);

            // find previous result from current run before query
            if (response == null) {
                String result = cache.query_cache(query.replaceAll("\\|", " "));
                if (result != null) {
                    String[] splited = result.split(" ");
                    String res_prefix;
                    String res_suffix;
                    res_prefix = splited[0];
                    for (int i = 1; i < prefLen; i++) {
                        res_prefix += " " + splited[i];
                    }
                    res_suffix = splited[prefLen];
                    if (prefLen + 1 < result.length()) {
                        for (int i = prefLen + 1; i < splited.length; i++) {
                            res_suffix += " " + splited[i];
                        }
                    }
                    response = res_prefix + "|" + res_suffix;
                    System.out.println("found in cache " + response);
                }
            }

            // Query was found in the query resumer
            // Resume becomes true when it is found in the map and correctly loads the corresponding result
            if (response != null) {
                System.out.println("Found in previous log. Response = " + response);

                String[] str_prefix;
                String[] str_suffix;

                try {
                    str_prefix = response.split("\\|")[0].split(" ");
                    str_suffix = response.split("\\|")[1].split(" ");

                    int ctr = 0;
                    for (I sym : prefix) {
                        wbPrefix.add((D) str_prefix[ctr]);
                        ctr++;
                    }

                    ctr = 0;

                    for (I sym : suffix) {
                        wbSuffix.add((D) str_suffix[ctr]);
                        ctr++;
                    }

                    responseWordList.add(wbSuffix.toWord());
                    responseToStringList.add(wbSuffix.toWord().toString());
                    prefixToStringList.add(wbPrefix.toWord());
                    resumed = true;
                } catch (Exception e) {
                    System.out.println("ERROR: Incorrect resume log, skipping");
                    e.printStackTrace();
                    resumed = false;
                }
            }


        }

        // Only executes when the query has not been previously explored
        // ,an error occurred while loading the result from the resumer
        // or resumer is inactive
        if (!resumed || !config.resume_learning_active) {
            // If the resumer is active then display a message to let
            // the user know the query was not found in the log file
            if (config.resume_learning_active)
                System.out.println("Not found in previous log");

            // If the cache is active, we must execute the same query
            // three times to avoid inconsistency

            if (config.cache_active)
                num_of_repeated_queries = 2;

            int consistent_counter;

            for (int i = 0; i < num_of_repeated_queries; i++) {
                Boolean time_out_occured_in_enable_s1 = false;

                WordBuilder<D> wbTempPrefix;
                WordBuilder<D> wbTempSuffix;

                String current_query;
                String current_result;
                String current_query_suffix;
                String current_result_suffix;

                Boolean consistent;
                consistent_counter = 0;
                do {
                    wbTempPrefix = new WordBuilder<>(prefix.length());
                    wbTempSuffix = new WordBuilder<>(suffix.length());
                    consistent = true;
                    // Invokes reset commands
                    this.sul.pre();
                    current_query = "";
                    current_result = "";

                    try {
                        for (I sym : prefix) {
                            if (!consistent)
                                break;

                            current_query += " " + sym;
                            current_query = current_query.trim();

                            String result = (String) this.sul.step(sym);

                            wbTempPrefix.add((D) result);

                            current_result += " " + result;
                            current_result = current_result.trim();
                            //System.out.println("Current Query IK= " + current_query);
                            String[] split = current_query.split("\\s+");

                            if (config.cache_active) {
                                // Looks up the current on going query to detect early inconsistency
//                                System.out.println("Cache active!");
//                                System.out.println("Current Query: " + current_query);
                                String result_in_cache = cache.query_cache(current_query);
//                                System.out.println("Obtained Result: " + current_result);
//                                System.out.println("Execpted Result: " + result_in_cache);
                                // If branch that is only executed when an inconsistency has been found
                                if (result_in_cache != null && !current_result.matches(result_in_cache)) {
                                    //System.out.println("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$");
                                    System.out.println("Inconsistency in prefix, retrying from beginning");
                                    System.out.println("Current Query: " + current_query);
                                    System.out.println("Obtained Result: " + current_result);
                                    System.out.println("Execpted Result: " + result_in_cache);
                                    consistent = false;
                                    try (FileWriter fw = new FileWriter("Inconsistent Query.txt", true);
                                         BufferedWriter bw = new BufferedWriter(fw);
                                         PrintWriter out = new PrintWriter(bw)) {
                                        out.println("Current Query: " + current_query + "\n" + "Current Result:" + current_result + "\n" + "Result in Cache:" + result_in_cache + "\n");
                                    } catch (IOException e) {
                                        System.out.println("File not found!");
                                    }
                                    consistent_counter++;
                                    System.out.println("!!!!!!!!! Consistent counter = " + consistent_counter + " !!!!!!!!!!!");
                                    if (consistent_counter > 3) {
                                        CoreSUL.IMSI_OFFSET = 20;
                                    }
                                }
                            }
                        }

                        current_query_suffix = current_query;
                        current_result_suffix = current_result;

                        // Suffix: Execute symbols, outputs constitute output word
                        for (I sym : suffix) {
                            if (!consistent)
                                break;

                            current_query_suffix += " " + sym;
                            current_query_suffix = current_query_suffix.trim();

                            String result = (String) this.sul.step(sym);

                            wbTempSuffix.add((D) result);
                            current_result_suffix += " " + result;
                            current_result_suffix = current_result_suffix.trim();
                            //System.out.println("Current Query IK= " + current_query_suffix);
                            String[] split = current_query_suffix.split("\\s+");
                            //System.out.println("Current Query 1st IK= " + split[0]);

                            if (config.cache_active) {
                                // Looks up the current on going query to detect early inconsistency
                                //System.out.println("Cache active!");
                                String result_in_cache = cache.query_cache(current_query_suffix);
                                //System.out.println("Current Query: " + current_query_suffix);
                                //System.out.println("Obtained Result: " + current_result_suffix);
                                //System.out.println("Execpted Result: " + result_in_cache);
                                // If branch that is only executed when an inconsistency has been found
                                if (result_in_cache != null && !current_result_suffix.matches(result_in_cache)) {
                                    //System.out.println("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$");
                                    System.out.println("Inconsistency in prefix, retrying from beginning");
                                    System.out.println("Current Query: " + current_query_suffix);
                                    System.out.println("Obtained Result: " + current_result_suffix);
                                    System.out.println("Execpted Result: " + result_in_cache);
                                    consistent = false;
                                    try (FileWriter fw = new FileWriter("Inconsistent Query.txt", true);
                                         BufferedWriter bw = new BufferedWriter(fw);
                                         PrintWriter out = new PrintWriter(bw)) {
                                        out.println("Current Query: " + current_query_suffix + "\n" + "Current Result:" + current_result_suffix + "\n" + "Result in Cache:" + result_in_cache + "\n");
                                    } catch (IOException e) {
                                        System.out.println("File not found!");
                                    }
                                    consistent_counter++;
                                    System.out.println("!!!!!!!!! Consistent counter = " + consistent_counter + " !!!!!!!!!!!");
                                }
                            }

                            System.out.println("QUERY # " + (i + 1) + " / 3");
                            System.out.println("[" + prefix + " | " + suffix + " / " + wbTempPrefix.toWord() + " | " + wbTempSuffix.toWord() + "]");
                        }


                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    } finally {
                        sul.post();
                    }

                } while (!consistent);

                prefixToStringList.add(wbTempPrefix.toWord());
                responseWordList.add(wbTempSuffix.toWord());
                responseToStringList.add(wbTempSuffix.toWord().toString());
                if (responseToStringList.size() == 2) {
                    if (!responseToStringList.get(0).equals(responseToStringList.get(1))) {
                        String lastSymbol0 = responseWordList.get(0).toString().trim().substring(responseWordList.get(0).toString().trim().lastIndexOf(" ") + 1);
                        String lastSymbol1 = responseWordList.get(1).toString().trim().substring(responseWordList.get(1).toString().trim().lastIndexOf(" ") + 1);

                        if (!lastSymbol0.equals("null_action") && lastSymbol1.equals("null_action")) {
                            responseToStringList.remove(1);
                            prefixToStringList.remove(1);
                            responseWordList.remove(1);
                            System.out.println("Found response msg in query 0");

                        } else if (!lastSymbol1.equals("null_action") && lastSymbol0.equals("null_action")) {
                            responseToStringList.remove(0);
                            prefixToStringList.remove(0);
                            responseWordList.remove(0);
                            System.out.println("Found response msg in query 1");
                        } else {
                            try (BufferedWriter bw1 = new BufferedWriter(new FileWriter("inconsistent.log", true))) {
                                bw1.append("Pair Start" + '\n');
                                String out = "[" + prefix + " | " + suffix + " / " +
                                        prefixToStringList.get(0).toString() + " | " +
                                        responseWordList.get(0).toString() + "]";
                                bw1.append(out + '\n');
                                String out1 = "[" + prefix + " | " + suffix + " / " +
                                        prefixToStringList.get(1).toString() + " | " +
                                        responseWordList.get(1).toString() + "]";
                                bw1.append(out1 + '\n');
                                System.out.println("Found Inconsistency in 2 run Queries!!");
                                CoreSUL.IMSI_OFFSET = 20;
                                num_of_repeated_queries = 3;
                            } catch (Exception e) {
                                System.err.println("ERROR: Could not update inconsistent log");

                            }
                        }
                    }
                }
            }
        }

        // Obtains the most common answer
        String mostRepeatedResponse = responseToStringList.stream()
                .collect(Collectors.groupingBy(w -> w, Collectors.counting()))
                .entrySet()
                .stream()
                .max(Comparator.comparing(Map.Entry::getValue))
                .get()
                .getKey();

        logger.logQuery("[" + prefix + " | " + suffix + " / " +
                prefixToStringList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString() + " | " +
                responseWordList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString() + "]");

        File f2 = new File(logger.getName() + ".log");
        try {
            if (f2.createNewFile()) {
                System.out.println(logger.getName() + ".log file has been created.");
            }
            PrintWriter writer2 = new PrintWriter(f2);
            writer2.print("[" + prefix + " | " + suffix + " / " +
                    prefixToStringList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString() + " | " +
                    responseWordList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString() + "]");
            writer2.close();
        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        for (int i = 0; i < responseWordList.size(); i++) {
            System.out.println("[" + prefix + " | " + suffix + " / " +
                    prefixToStringList.get(i).toString() + " | " +
                    responseWordList.get(i).toString() + "]");
            //System.out.println(responseToStringList.get(i));

        }
        if (config.resume_learning_active) {
            String query = prefix + "|" + suffix;
            String result = prefixToStringList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString()
                    + "|" + responseWordList.get(responseToStringList.indexOf(mostRepeatedResponse)).toString();
            learning_resumer.add_Entry("INFO: [" + query + "/" + result + "]");
        }

        return responseWordList.get(responseToStringList.indexOf(mostRepeatedResponse));
    }

    @Override
    public Word<D> answerQuery(Word<I> prefix, Word<I> suffix) {
        return answerQuerySteps(prefix, suffix);
    }

    @Override
    public Word<D> answerQuery(Word<I> query) {
        return answerQuery(Word.epsilon(), query);
    }

    @Override
    public void processQueries(Collection<? extends Query<I, Word<D>>> queries) {
        for (Query<I, Word<D>> q : queries) {
            Word<D> output = answerQuery(q.getPrefix(), q.getSuffix());
            q.answer(output);
        }
    }

    public static class MealyLogOracle<I, O> extends LogOracle<I, O> {
        public MealyLogOracle(StateLearnerSUL<I, O> sul, LearnLogger logger) {
            super(sul, logger);
        }
    }
}

