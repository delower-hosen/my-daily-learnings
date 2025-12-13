package com.example.camel_microservice_a.beans;

import org.springframework.stereotype.Component;

@Component("timeEnhancer")
public class TimeEnhancerBean {
    public String invoke(String body) {
        return "[Processed] " + body;
    }
}
