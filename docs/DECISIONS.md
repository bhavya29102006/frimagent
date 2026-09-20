# DECISIONS (override other docs where they conflict)
1. Minimum generated tests = 12.
2. Category names as in agent/models.py: normal, boundary, abnormal,
   sensor_failure, recovery, sequence, combination, followup.
3. Sensor disconnect = static diagram variant (SDA wire removed) for the
   whole run. Reconnect mid-run is NOT supported, so R6 is reported as
   "not testable in simulator".
4. "recovery" = from a hot state (65 -> 25), not sensor reconnect.
5. "abnormal" = extreme valid DHT22 values (-40, 80, 59.9, 60.0) and
   rapid changes. Values outside -40..80 cannot be simulated.
6. Uploaded firmware = analysis + test generation only. Execution only
   for the bundled demo project.
7. PASS/FAIL only in evaluator.py. Non-zero wokwi-cli exit = expectation
   not met (default timeout exit code is 42).
   8. Verified on real runs: passing scenario prints "Scenario completed
   successfully" and exits 0. A failing scenario prints "Timeout: simulation
   did not finish in Nms" and exits non-zero. Stdout contains the serial lines
   plus "Expected text matched" lines prefixed with the scenario name.
      9. R2 clarified: with fan ON, at exactly 28.0 C the fan turns OFF (<= 28.0).
      Above 28.0 it stays ON.