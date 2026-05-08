       IDENTIFICATION DIVISION.
       PROGRAM-ID. ComprehensiveTest.
       AUTHOR.  TestUser.
       DATE-WRITTEN. 2025-12-28.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.

       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MOCK-FILE ASSIGN TO "DUMMY.DAT"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FILE-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  MOCK-FILE.
       01  MOCK-RECORD.
           05  MOCK-ID       PIC 9(05).
           05  MOCK-NAME     PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-FILE-STATUS    PIC XX.
           05  WS-EOF            PIC X VALUE 'N'.
               88 END-OF-FILE    VALUE 'Y'.
           05  WS-VALID-DATA     PIC X VALUE 'N'.
               88 IS-VALID       VALUE 'Y'.

       01  WS-COUNTERS.
           05  WS-IDX            PIC 9(02) VALUE 0.
           05  WS-SUB-IDX        PIC 9(02) VALUE 0.
           05  WS-TOTAL          PIC 9(04) VALUE 0.

       01  WS-TABLE-DATA.
           05  WS-GROUP OCCURS 5 TIMES INDEXED BY I.
               10  WS-ELEM       PIC X(10).
               10  WS-NUM        PIC 9(03).

       01  WS-STRINGS.
           05  WS-FULL-NAME      PIC X(30).
           05  WS-FIRST          PIC X(10) VALUE "JOHN".
           05  WS-LAST           PIC X(10) VALUE "DOE".

       01  WS-CALC-VARS.
           05  WS-A              PIC 9(03) VALUE 10.
           05  WS-B              PIC 9(03) VALUE 20.
           05  WS-RESULT         PIC 9(04).

       LINKAGE SECTION.
       01  LK-PARAM          PIC X(10).

       PROCEDURE DIVISION USING LK-PARAM.
       000-MAIN-LOGIC.
           PERFORM 100-INITIALIZATION
           PERFORM 200-PROCESS-DATA UNTIL WS-IDX > 5
           PERFORM 300-COMPLEX-LOGIC
           PERFORM 400-STRING-OPS
           PERFORM 900-CLEANUP
           STOP RUN.

       100-INITIALIZATION.
           DISPLAY "Initializing Program..."
           MOVE "START" TO WS-FULL-NAME
           INITIALIZE WS-TABLE-DATA
           PERFORM VARYING I FROM 1 BY 1 UNTIL I > 5
               MOVE "ITEM" TO WS-ELEM(I)
               COMPUTE WS-NUM(I) = I * 10
           END-PERFORM.

       200-PROCESS-DATA.
           ADD 1 TO WS-IDX
           DISPLAY "Processing Index: " WS-IDX
           
           IF WS-IDX = 3
               DISPLAY "  -> Critical Index Reached (GoTo Logic)"
               GO TO 250-SPECIAL-CASE
           END-IF

           IF WS-IDX > 3
               PERFORM 210-SUB-LOOP
           ELSE
               DISPLAY "  -> Normal Path"
           END-IF.

           EXIT.

       250-SPECIAL-CASE.
           DISPLAY "  -> Executing Special Branch"
           COMPUTE WS-TOTAL = WS-TOTAL + 500.

       210-SUB-LOOP.
           PERFORM VARYING WS-SUB-IDX FROM 1 BY 1 UNTIL WS-SUB-IDX > 3
               EVALUATE WS-SUB-IDX
                   WHEN 1
                       DISPLAY "    -> Sub-Loop Phase 1: Start"
                   WHEN 2
                       DISPLAY "    -> Sub-Loop Phase 2: Middle"
                   WHEN OTHER
                       DISPLAY "    -> Sub-Loop Phase 3: End"
               END-EVALUATE
           END-PERFORM.

       300-COMPLEX-LOGIC.
           DISPLAY "--- Start Complex Logic ---"
           EVALUATE TRUE
               WHEN WS-A < WS-B AND WS-IDX > 2
                   DISPLAY "Condition 1 Met: A < B and Loops Done"
                   COMPUTE WS-RESULT = (WS-A + WS-B) * 2
               WHEN WS-A = 10 OR WS-B = 99
                   DISPLAY "Condition 2 Met: Default Values"
               WHEN OTHER
                   DISPLAY "No Conditions Met"
           END-EVALUATE.

       400-STRING-OPS.
           DISPLAY "--- String Operations ---"
           STRING WS-FIRST DELIMITED BY SPACE
                  " " DELIMITED BY SIZE
                  WS-LAST DELIMITED BY SPACE
                  INTO WS-FULL-NAME
           END-STRING
           DISPLAY "Concatenated Name: " WS-FULL-NAME
           
           INSPECT WS-FULL-NAME REPLACING ALL "O" BY "0".
           DISPLAY "Inspected Name:    " WS-FULL-NAME.

       900-CLEANUP.
           DISPLAY "--- Cleanup ---"
           IF WS-FILE-STATUS = "00"
               CLOSE MOCK-FILE
           ELSE
               DISPLAY "File was never opened, skipping close."
           END-IF.
           DISPLAY "Program Completed.".
