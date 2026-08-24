package org.example.corelearner;


import java.io.*;
import java.sql.*;
import java.util.HashMap;
import java.util.Map;


public class LearningResumer {
    static final String url = "jdbc:sqlite:my_database.sqlite";
    public LearningConfig config = null;
    String learning_log;

    public LearningResumer(String learning_log) {
        this.learning_log = learning_log;
        load_learning_log();
    }

    private void load_learning_log() {
        Connection myConn = null;
        try {
            Class.forName("org.sqlite.JDBC");
            myConn = DriverManager.getConnection(url);
            config = new LearningConfig("core.properties");
        } catch (Exception e) {
            System.out.println("DB Connection Error!");
            e.printStackTrace();
        }

        try {

            String sql = "SELECT * FROM queryNew_" + config.device;
            assert myConn != null;
            Statement stmt = myConn.createStatement();
            stmt.executeQuery(sql);
        } catch (Exception e) {
            System.out.println("$$$$$$$$$$$$$$$$$");
            try {
                String create = "CREATE TABLE \"queryNew_" + config.device + "\"" + "(\"command\"   TEXT, \"result\"    TEXT, PRIMARY KEY(\"command\"))";
                Statement stmt = myConn.createStatement();
                stmt.executeUpdate(create);
            } catch (Exception ex) {
                System.out.println("Failed to create table");
            }
        }
        try {

            String sql = "SELECT * FROM query_" + config.device;
            Statement stmt = myConn.createStatement();
            stmt.executeQuery(sql);
        } catch (Exception e) {
            System.out.println("$$$$$$$$$$$$$$$$$");
            try {
                String create = "CREATE TABLE \"query_" + config.device + "\"" + "(\"command\"  TEXT, \"result\"    TEXT, PRIMARY KEY(\"command\"))";
                Statement stmt = myConn.createStatement();
                stmt.executeUpdate(create);
            } catch (Exception ex) {
                System.out.println("Failed to create table");
            }
        }
        try {
            //check query* is empty or not
            String sql = "SELECT * FROM queryNew_" + config.device;
            Statement stmt = myConn.createStatement();
            ResultSet rs = stmt.executeQuery(sql);
            if (rs.next()) {
                //There are some entry in query*
                //Copy everything from query* in query
                Statement st = myConn.createStatement();

                Statement st1 = myConn.createStatement();
                rs = st1.executeQuery("select * from queryNew_" + config.device);
                PreparedStatement ps;

                while (rs.next()) {
                    try {
                        ps = myConn.prepareStatement("insert into query_" + config.device + " (command, result) values(?,?)");
                        // System.out.println("data here "+rs.getString("id"));
                        ps.setString(1, rs.getString("command"));
                        ps.setString(2, rs.getString("result"));
                        ps.executeUpdate();
                        ps.close();
                    } catch (SQLException e) {
                        //System.out.println("Duplicate Entry!");
                        //e.printStackTrace();
                        //Got a duplicate basically
                    }
                }

                //Delete everything from query*
                sql = "delete from queryNew_" + config.device + " where 1=1";
                st.executeUpdate(sql);
                System.out.println("Deleted all entries in queryNew");
                st1.close();
                stmt.close();
            }
            File f = new File(this.learning_log);
            if (f.createNewFile()) {

                System.out.println(this.learning_log + " file has been created.");
            } else {

                System.out.println(this.learning_log + " file already exists.");
                System.out.println("Reading learning log: " + this.learning_log);
                PrintWriter writer = new PrintWriter(f);
                writer.print("");
                writer.close();
            }

            myConn.close();

        } catch (IOException e) {
            e.printStackTrace();
        } catch (SQLException e) {
            System.err.println("Duplicate Entry!");
            e.printStackTrace();
        }

    }

    public String query_resumer(String command, int prefLen) {
        Connection myConn = null;
        try {
            Class.forName("org.sqlite.JDBC");
            myConn = DriverManager.getConnection(url);
        } catch (Exception e) {
            System.out.println("DB Connection Error!");
            e.printStackTrace();
        }
        System.out.println("In query resumer, looking for: " + command);
        String query = "select * from query_" + config.device + " where command = ?";
        command = command.replaceAll("\\|", " ");
        try {
            PreparedStatement preparedstatement = myConn.prepareStatement(query);
            preparedstatement.setString(1, command);
            ResultSet rs = preparedstatement.executeQuery();
            if (rs.next()) {
                String fromDB = rs.getString("result");
                String[] splited = fromDB.split(" ");
                String prefix;
                String suffix;
                prefix = splited[0];
                for (int i = 1; i < prefLen; i++) {
                    prefix += " " + splited[i];
                }
                suffix = splited[prefLen];
                if (prefLen + 1 < fromDB.length()) {
                    for (int i = prefLen + 1; i < splited.length; i++) {
                        suffix += " " + splited[i];
                    }
                }


                System.out.println("found in log " + prefix + "|" + suffix);

                try {
                    String query2 = " insert into queryNew_" + config.device + " (command, result)"
                            + " values (?, ?)";
                    PreparedStatement preparedstatement2 = myConn.prepareStatement(query2);
                    preparedstatement2.setString(1, rs.getString("command"));
                    preparedstatement2.setString(2, rs.getString("result"));
                    preparedstatement2.execute();
                    preparedstatement.close();
                    preparedstatement2.close();
                } catch (Exception e) {
                    myConn.close();
                    System.out.println("Already exists in queryNew!");
                }
                myConn.close();
                return prefix + "|" + suffix;
            } else {
                return null;
            }
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    public void add_Entry(String entry) {
        Connection myConn = null;
        try {
            Class.forName("org.sqlite.JDBC");
            myConn = DriverManager.getConnection(url);
        } catch (Exception e) {
            System.out.println("DB Connection Error!");
            e.printStackTrace();
        }
        System.out.println("In add!");
        try (BufferedWriter bw = new BufferedWriter(new FileWriter(this.learning_log, true))) {
            bw.append(entry + '\n');

        } catch (Exception e) {
            System.err.println("ERROR: Could not update learning log");
        }
        try {
            String command = entry.split("/")[0].split("\\[")[1];
            String result = entry.split("/")[1].split("]")[0];
            command = String.join(" ", command.split("\\s+"));
            result = String.join(" ", result.split("\\s+"));
            String query = " insert into queryNew_" + config.device + " (command, result)"
                    + " values (?, ?)";
            command = command.replaceAll("\\|", " ");
            result = result.replaceAll("\\|", " ");
            System.out.println("OUTPUT: " + command + " " + result);

            PreparedStatement preparedStmt = myConn.prepareStatement(query);
            preparedStmt.setString(1, command);
            preparedStmt.setString(2, result);
            preparedStmt.execute();
            myConn.close();
            System.out.println("Added to DB! in Resumer");
        } catch (SQLException e) {
            System.out.println("history already exist in Add_Entry in QueryNew (Learning Resumer)!!");
            //e.printStackTrace();
        } catch (Exception e) {
            System.out.println("DB add_Entry Error!");
            e.printStackTrace();
        }
    }
}

