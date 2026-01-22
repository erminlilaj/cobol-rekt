       IDENTIFICATION DIVISION.
       PROGRAM-ID. STUDENT-GRADES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CURRENT-SEMESTER       PIC XXXX VALUE "FALL".
      *
      * An array of Student Scores to SEARCH
       01  STUDENT-SCORES-TABLE.
           10 STUDENT-ENTRY       OCCURS 10 INDEXED BY IDX.
              20 STU-ID           PIC 9999.
              20 STU-SCORE        PIC 999.

      * Nested variables for generic counters
       01  COUNTERS.
           10 ROW-COUNTER         PIC 99.
           10 SEAT-COUNTER        PIC 99.
           10 EXAM-WEIGHT         PIC 9999.
           10 EXTRA-CREDIT        PIC 9999.

      * A 2D Array representing a Classroom Seating Chart
       01  CLASSROOM-LAYOUT.
           10 CLASS-ROW           OCCURS 3.
              20 SEAT-Assignment  PIC XXXX.
           10 LAB-SECTION         OCCURS 2.
              20 LAB-COMPUTERS    PIC XXXX OCCURS 2.
       
      * Redefines for specific data views
       01  RAW-DATA               PIC XXXX.
       01  RAW-NUMERIC REDEFINES RAW-DATA PIC 9999.

      * Variables for Arithmetic Logic
       01  CALCULATED-GPA         PIC S99V9.
       01  TEXT-GPA REDEFINES CALCULATED-GPA PIC XXX.
       
      * Variables for Conditional Logic
       01  ATTENDANCE-DAYS        PIC 999.
       01  MAX-DAYS REDEFINES ATTENDANCE-DAYS PIC 9999.
       01  PARTICIPATION-PTS      PIC 99PP.
       
      * The Switch Variable for the GO TO Graph
       01  STUDENT-YEAR-LEVEL     PIC 99999.

      * Boolean Flags (88 Levels)
       01  EXAM-RESULT            PIC X VALUE "P".
           88 PASSED              VALUE "P".
           88 FAILED              VALUE "F".

       LINKAGE SECTION.
       01  EXTERNAL-DATA          PIC X(99999).
       01  LINKED-ID              PIC XXXX.
       01  LINKED-SCORES          PIC 9999 OCCURS 2.

       PROCEDURE DIVISION.
       
      * -----------------------------------------------------------
      * MAIN LOGIC ROUTER
      * -----------------------------------------------------------
       SECTION-0 SECTION.
       P1.
      * 1. EVALUATE: Categorize the Grade (Branching Logic)
           EVALUATE TRUE ALSO TRUE
               WHEN PARTICIPATION-PTS + STUDENT-YEAR-LEVEL < 10 
                    ALSO EXAM-WEIGHT = 10
                    MOVE "FAIL" TO RAW-DATA
               WHEN PARTICIPATION-PTS + STUDENT-YEAR-LEVEL > 50 
                    ALSO EXAM-WEIGHT = ( CALCULATED-GPA + 
                    STUDENT-YEAR-LEVEL ) / PARTICIPATION-PTS
                    MOVE "PASS" TO RAW-DATA
               WHEN OTHER
                    MOVE "WAIT" TO RAW-DATA
           END-EVALUATE.

      * 2. SEARCH: Linear search for a student score > 90
           SEARCH STUDENT-ENTRY
               WHEN STU-SCORE(IDX) > 90
                    DISPLAY "FOUND HONOR STUDENT"
               WHEN STU-SCORE(IDX) <= 50
                    DISPLAY "FOUND AT-RISK STUDENT"
           END-SEARCH.

      * 3. PERFORM: Nested Loop (Iterate Rows and Seats)
           PERFORM TEST BEFORE VARYING ROW-COUNTER FROM 1 BY 1
                   UNTIL ROW-COUNTER > 10
                   AFTER SEAT-COUNTER FROM 1 BY 1 
                   UNTIL SEAT-COUNTER > 10
               DISPLAY "CHECKING ROW " ROW-COUNTER " SEAT " SEAT-COUNTER
           END-PERFORM.

      * 4. GO TO DEPENDING: Route based on Student Year
      * 1 = SECTION-A (Freshman Calculation)
      * 2 = SECTION-B (Sophomore Check)
      * 3 = SECTION-B1 (Junior Check)
           GO TO SECTION-A, SECTION-B, SECTION-B1 
                 DEPENDING ON STUDENT-YEAR-LEVEL.

      * -----------------------------------------------------------
      * LOGIC FOR FRESHMEN (Calculations)
      * -----------------------------------------------------------
       SECTION-A SECTION.
       P2.
           ADD CALCULATED-GPA, PARTICIPATION-PTS, 30 
               TO RAW-NUMERIC, STUDENT-YEAR-LEVEL.
           
      * Initialize Seating Chart
           MOVE "JDOE" TO SEAT-Assignment(1).
           MOVE "MSMI" TO SEAT-Assignment(2).
           MOVE "ALEE" TO SEAT-Assignment(3).

       P3.
      * Matrix Operations (2D Array Access)
           MOVE "PC01" TO LAB-COMPUTERS(1 1).
           MOVE "PC02" TO LAB-COMPUTERS(1 2).
           MOVE "PC03" TO LAB-COMPUTERS(2 1).
           MOVE "PC04" TO LAB-COMPUTERS(2 2).
           
           DISPLAY "LAB SETUP COMPLETE".

      * Arithmetic Graph Nodes
           ADD 1 TO 1 GIVING CALCULATED-GPA.
           DIVIDE 10 INTO CALCULATED-GPA.
           ADD 1 TO 1 GIVING CALCULATED-GPA.
           SUBTRACT 5 FROM 30 GIVING CALCULATED-GPA.
           MULTIPLY 2 BY 2 GIVING EXAM-WEIGHT.

       P4.
      * Complex Computation
           ADD CALCULATED-GPA TO CALCULATED-GPA.
           MOVE 10 TO LINKED-SCORES(1).
           COMPUTE CALCULATED-GPA = 2 * CALCULATED-GPA + 1.
           COMPUTE CALCULATED-GPA = CALCULATED-GPA / LINKED-SCORES(1).

      * -----------------------------------------------------------
      * LOGIC FOR SOPHOMORES (Pass/Fail Check)
      * -----------------------------------------------------------
       SECTION-B SECTION.
       P5.
           DISPLAY "CURRENT GPA = " CALCULATED-GPA.
           
      * Simple Decision Node
           IF (CALCULATED-GPA) = "3.0" OR "4.0"
               DISPLAY "GOOD STANDING"
           ELSE
               DISPLAY "PROBATION".
           
           DISPLAY "END OF TERM".

       P6.
      * Score Adjustments
           MOVE 100 TO LINKED-SCORES(1).
           ADD 0 TO LINKED-SCORES(1).
           SUBTRACT 0 FROM LINKED-SCORES(1).

      * -----------------------------------------------------------
      * LOGIC FOR JUNIORS (Duplicate Logic Path)
      * -----------------------------------------------------------
       SECTION-B1 SECTION.
       P7.
           DISPLAY "CURRENT GPA = " CALCULATED-GPA.
           
      * Simple Decision Node
           IF (CALCULATED-GPA) = "3.0" OR "4.0"
               DISPLAY "GOOD STANDING"
           ELSE
               DISPLAY "PROBATION".

       P8.
           MOVE 100 TO LINKED-SCORES(1).
           ADD 0 TO LINKED-SCORES(1).
           SUBTRACT 0 FROM LINKED-SCORES(1).

      * -----------------------------------------------------------
      * FINAL GRADE REPORTING
      * -----------------------------------------------------------
       SECTION-C SECTION.
       P9.
           DISPLAY "UNION CHECK = " RAW-DATA.
           MOVE 50 TO LINKED-SCORES(1).
           MOVE "PASS" TO RAW-DATA.
           MOVE "P" TO EXAM-RESULT.

       P10.
      * Complex Compound Conditions
      * Checks if Score is 10, or > 20 AND Passed
           IF (LINKED-SCORES(1) = 10) OR > 20 AND PASSED
               DISPLAY "GRADUATED WITH HONORS".
           
      * Checks for specific edge cases
           IF LINKED-SCORES(1) = 100 OR 30 OR 50
               DISPLAY "GRADUATED STANDARD".

           STOP RUN.
