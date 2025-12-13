package com.example.camel_microservice_a.beans;

import java.time.LocalTime;
import org.springframework.stereotype.Component;

@Component("currentTime")
public class CurrentTimeBean {
    public String invoke() {
        return "Time is now: " + LocalTime.now();
    }
}
