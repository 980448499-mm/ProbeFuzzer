package org.example.corelearner.db;

import org.example.corelearner.LearningConfig;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

public class Cache {

    public LearningConfig config = null;
    String cache_log = "";


    public Cache(String cache_log) {
        try {
            config = new LearningConfig("core.properties");
        } catch (Exception e) {
            System.out.println("Howcome!");
        }
        this.cache_log = cache_log;
    }

    public static void main(String[] args) {
        Cache myCache = new Cache("cache.log");
    }

    public Connection getCacheConnection() {
        return DBHelper.getConnection();
    }

    public String query_cache(String command) {
        Connection myConn = this.getCacheConnection();
        if (myConn == null) {
            System.out.println("*** IN Cache.query_cache(): Cache DB Connection not established ***");
        }

        if (command == null) {
            return null;
        }
        String Myquery = "select * from queryNew_" + config.device + " where command = ?";

        try {
            assert myConn != null;
            PreparedStatement preparedstatement = myConn.prepareStatement(Myquery);
            preparedstatement.setString(1, command);
            System.out.println("***** Search Command = " + command + " *****");
            ResultSet rs = preparedstatement.executeQuery();
            if (rs.next()) {
                String saved_query = rs.getString("result");
                preparedstatement.close();
                return saved_query;
            } else {
                Myquery = "select * from query_" + config.device + " where command = ?";
                preparedstatement = myConn.prepareStatement(Myquery);
                preparedstatement.setString(1, command);
                System.out.println("***** Search Command Old = " + command + " *****");
                rs = preparedstatement.executeQuery();
                if (rs.next()) {
                    String saved_query = rs.getString("result");
                    preparedstatement.close();
                    return saved_query;
                } else {
                    return null;
                }
            }
        } catch (Exception e) {
            return null;
        }

    }

}

