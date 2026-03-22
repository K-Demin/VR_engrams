// Arduino Uno firmware for direct opto train generation via serial commands.
//
// Serial command:
//   TRAIN <freq_hz> <pulse_ms> <duration_ms>\n
//
// Example:
//   TRAIN 20 15 60000
//
// Output:
//   TTL pulses on OPT_PIN (default D9), then reply "OK TRAIN"

static const int OPT_PIN = 9;

void setup() {
  pinMode(OPT_PIN, OUTPUT);
  digitalWrite(OPT_PIN, LOW);
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for serial on boards that need it
  }
  Serial.println("READY");
}

void runTrain(float freq_hz, float pulse_ms, unsigned long duration_ms) {
  if (freq_hz <= 0.0f) return;
  unsigned long period_us = (unsigned long)(1000000.0f / freq_hz);
  unsigned long high_us = (unsigned long)(pulse_ms * 1000.0f);
  if (high_us >= period_us) high_us = period_us - 1;
  unsigned long low_us = period_us - high_us;

  unsigned long start_ms = millis();
  while ((millis() - start_ms) < duration_ms) {
    digitalWrite(OPT_PIN, HIGH);
    delayMicroseconds(high_us);
    digitalWrite(OPT_PIN, LOW);
    delayMicroseconds(low_us);
  }
  digitalWrite(OPT_PIN, LOW);
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (!line.startsWith("TRAIN ")) {
    Serial.println("ERR UNKNOWN_CMD");
    return;
  }

  float freq_hz = 0.0f;
  float pulse_ms = 0.0f;
  unsigned long duration_ms = 0;

  int first = line.indexOf(' ');
  int second = line.indexOf(' ', first + 1);
  int third = line.indexOf(' ', second + 1);

  if (first < 0 || second < 0 || third < 0) {
    Serial.println("ERR BAD_ARGS");
    return;
  }

  freq_hz = line.substring(first + 1, second).toFloat();
  pulse_ms = line.substring(second + 1, third).toFloat();
  duration_ms = (unsigned long)line.substring(third + 1).toInt();

  if (freq_hz <= 0.0f || pulse_ms <= 0.0f || duration_ms == 0) {
    Serial.println("ERR BAD_VALUES");
    return;
  }

  runTrain(freq_hz, pulse_ms, duration_ms);
  Serial.println("OK TRAIN");
}
