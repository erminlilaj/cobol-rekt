package org.smojol.common.vm.memory;

import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;
import org.apache.commons.lang3.tuple.ImmutablePair;
import org.apache.commons.lang3.tuple.Pair;
import org.eclipse.lsp.cobol.core.CobolDataTypes;
import org.eclipse.lsp.cobol.core.CobolDataTypesLexer;
import org.smojol.common.vm.type.ZonedDecimalSignType;
import org.smojol.common.vm.type.AlphanumericDataTypeSpec;
import org.smojol.common.vm.type.DataTypeSpec;
import org.smojol.common.vm.type.ZonedDecimalDataTypeSpec;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

public class DataLayoutBuilder {
    private static final Logger LOGGER = Logger.getLogger(DataLayoutBuilder.class.getName());

    public record PicParseResult(CobolDataTypes.StartRuleContext tree, List<String> errors) {}

    public MemoryLayout layout(String spec) {
        CobolDataTypes.StartRuleContext root = parseSpec(spec);
        return build(typeSpec(root.dataTypeSpec()));
    }

    private Pair<DataTypeSpec, Integer> typeSpec(CobolDataTypes.DataTypeSpecContext dataTypeSpecContext) {
        if (dataTypeSpecContext.alphanumeric() != null) return alphanumericLayout(dataTypeSpecContext);
        return numeric(dataTypeSpecContext);
    }

    private MemoryLayout build(Pair<DataTypeSpec, Integer> typeSpec) {
        MemoryRegion region = new MemoryRegion(typeSpec.getRight());
        return new MemoryLayout(region.fullAccess(), typeSpec.getLeft());
    }

    private ImmutablePair<DataTypeSpec, Integer> numeric(CobolDataTypes.DataTypeSpecContext spec) {
        CobolDataTypes.FractionContext fractionCtx = spec.fraction();
        ZonedDecimalSignType signType = fractionCtx.SIGN_SYMBOL() != null ? ZonedDecimalSignType.SIGNED : ZonedDecimalSignType.UNSIGNED;
        Pair<Integer, Integer> leftRight = numChars(fractionCtx);
        ZonedDecimalDataTypeSpec numericType = new ZonedDecimalDataTypeSpec(leftRight.getLeft(), leftRight.getRight(), signType);
        int totalChars = leftRight.getRight() + leftRight.getLeft();
        return new ImmutablePair<>(numericType, totalChars);
    }

    private ImmutablePair<DataTypeSpec, Integer> alphanumericLayout(CobolDataTypes.DataTypeSpecContext spec) {
        CobolDataTypes.AlphanumericContext alphanumeric = spec.alphanumeric();
        List<CobolDataTypes.LeftSideAlphanumericIndicatorContext> leftSide = alphanumeric.leftSideAlphanumericIndicator();
        List<CobolDataTypes.RightSideAlphanumericIndicatorContext> rightSide = alphanumeric.rightSideAlphanumericIndicator();
        int centerChars = numChars(alphanumeric.alphaNumericIndicator());
        Integer leftChars = leftSide.stream().map(this::numChars).reduce(0, Integer::sum);
        Integer rightChars = rightSide.stream().map(this::numChars).reduce(0, Integer::sum);
        int totalChars = leftChars + centerChars + rightChars;
        AlphanumericDataTypeSpec typeSpec = new AlphanumericDataTypeSpec(totalChars);
        return new ImmutablePair<>(typeSpec, totalChars);
    }

    private Pair<Integer, Integer> numChars(CobolDataTypes.FractionContext fractionCtx) {
        if (fractionCtx.integer() != null) {
            Integer leftSide = numChars(fractionCtx.integer().digitIndicator());
            Integer rightSide = 0;
            return new ImmutablePair<>(leftSide, rightSide);
        } else if (fractionCtx.onlyLeftOfDecimalPoint() != null) {
            List<CobolDataTypes.DigitIndicatorContext> indicators = fractionCtx.onlyLeftOfDecimalPoint().integerPart().digitIndicator();
            Integer leftSide = numChars(indicators);
            Integer rightSide = 0;
            return new ImmutablePair<>(leftSide, rightSide);
        } else if (fractionCtx.onlyRightOfDecimalPoint() != null) {
            List<CobolDataTypes.DigitIndicatorContext> indicators = fractionCtx.onlyRightOfDecimalPoint().fractionalPart().digitIndicator();
            Integer leftSide = 0;
            Integer rightSide = numChars(indicators);
            return new ImmutablePair<>(leftSide, rightSide);
        } else {
            Integer leftSide = numChars(fractionCtx.bothSidesOfDecimalPoint().integerPart().digitIndicator());
            Integer rightSide = numChars(fractionCtx.bothSidesOfDecimalPoint().fractionalPart().digitIndicator());
            return new ImmutablePair<>(leftSide, rightSide);
        }
    }

    private Integer numChars(List<CobolDataTypes.DigitIndicatorContext> indicators) {
        return indicators.stream().map(this::numChars).reduce(0, Integer::sum);
    }

    private int numChars(CobolDataTypes.RightSideAlphanumericIndicatorContext indicator) {
        if (indicator.alphaNumericIndicator() != null) return numChars(indicator.alphaNumericIndicator());
        return numChars(indicator.digitIndicator());
    }

    private int numChars(CobolDataTypes.LeftSideAlphanumericIndicatorContext indicator) {
        if (indicator.alphaNumericIndicator() != null) return numChars(indicator.alphaNumericIndicator());
        return numChars(indicator.digitIndicator());
    }

    private int numChars(CobolDataTypes.DigitIndicatorContext digitIndicator) {
        return digitIndicator.numberTypeIndicator() != null ? 1 : Integer.parseInt(digitIndicator.ndigits().numberOf().getText().replace("(", "").replace(")", ""));
    }

    private int numChars(CobolDataTypes.AlphaNumericIndicatorContext alphanumericIndicator) {
        return alphanumericIndicator.charTypeIndicator() != null ? 1 : Integer.parseInt(alphanumericIndicator.nchars().numberOf().getText().replace("(", "").replace(")", ""));
    }

    public static CobolDataTypes.StartRuleContext parseSpec(String spec) {
        CobolDataTypesLexer antlrLexer = new CobolDataTypesLexer(CharStreams.fromString(spec));
        antlrLexer.removeErrorListeners();
        CommonTokenStream tokenStream = new CommonTokenStream(antlrLexer);
        CobolDataTypes antlrParser = new CobolDataTypes(tokenStream);
        antlrParser.removeErrorListeners();
        return antlrParser.startRule();
    }

    public static PicParseResult parseSpecWithDiagnostics(String spec) {
        List<String> errors = new ArrayList<>();
        CobolDataTypesLexer antlrLexer = new CobolDataTypesLexer(CharStreams.fromString(spec));
        antlrLexer.removeErrorListeners();
        antlrLexer.addErrorListener(new BaseErrorListener() {
            @Override
            public void syntaxError(Recognizer<?, ?> r, Object o, int line, int pos, String msg, RecognitionException e) {
                errors.add("PIC '" + spec + "' lexer error at " + pos + ": " + msg);
            }
        });
        CommonTokenStream tokenStream = new CommonTokenStream(antlrLexer);
        CobolDataTypes antlrParser = new CobolDataTypes(tokenStream);
        antlrParser.removeErrorListeners();
        antlrParser.addErrorListener(new BaseErrorListener() {
            @Override
            public void syntaxError(Recognizer<?, ?> r, Object o, int line, int pos, String msg, RecognitionException e) {
                errors.add("PIC '" + spec + "' parse error at " + pos + ": " + msg);
            }
        });
        return new PicParseResult(antlrParser.startRule(), errors);
    }

    public Pair<DataTypeSpec, Integer> size(String spec) {
        PicParseResult result = parseSpecWithDiagnostics(spec);
        if (!result.errors().isEmpty()) {
            LOGGER.warning("PIC clause errors for '" + spec + "': " + result.errors());
        }
        Pair<DataTypeSpec, Integer> typeSpec = typeSpec(result.tree().dataTypeSpec());
        return typeSpec;
    }
}
