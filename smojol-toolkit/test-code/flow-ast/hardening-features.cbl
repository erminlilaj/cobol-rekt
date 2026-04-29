       IDENTIFICATION DIVISION.
       PROGRAM-ID. HARDENING-FEATURES.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           01  SRC-FIELD       PIC X(10) VALUE "AB CD".
           01  DEST-FIELD      PIC X(10).
           01  PART-1          PIC X(05).
           01  PART-2          PIC X(05).
           01  SWITCH-FLAG     PIC 9 VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE SWITCH-FLAG
               WHEN 1
                   STRING PART-1 DELIMITED BY SIZE
                          PART-2 DELIMITED BY SIZE
                      INTO DEST-FIELD
               WHEN OTHER
                   UNSTRING SRC-FIELD
                       DELIMITED BY ALL SPACE
                       INTO PART-1 PART-2
           END-EVALUATE
           ALTER OLD-PARA TO PROCEED TO NEW-PARA
           EXIT PARAGRAPH.
       OLD-PARA.
           DISPLAY "OLD".
       NEW-PARA.
           GOBACK.
