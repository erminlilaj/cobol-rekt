       IDENTIFICATION DIVISION.
       PROGRAM-ID. PICGATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INT PIC 9.
       01 WS-FIT-DEC PIC 9V9.
       01 WS-DEC-OVER PIC 9V9.
       01 WS-UNSIGNED PIC 9(2).
       01 WS-SIGNED PIC S9(2).
       01 WS-SOURCE PIC 9(2).
       01 WS-COPY-OVER PIC 9.
       01 WS-SIZE PIC 9(2).
       01 WS-ROUNDED PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-INT = 7 / 2
           COMPUTE WS-FIT-DEC = 7 / 2
           COMPUTE WS-DEC-OVER = 1 / 4
           COMPUTE WS-UNSIGNED = 0 - 1
           COMPUTE WS-SIGNED = 0 - 1
           MOVE 99 TO WS-SOURCE
           MOVE WS-SOURCE TO WS-COPY-OVER
           COMPUTE WS-SIZE = 1 + 2
               ON SIZE ERROR
                   MOVE 0 TO WS-SIZE
           END-COMPUTE
           COMPUTE WS-ROUNDED ROUNDED = 1 / 4
           GOBACK.
