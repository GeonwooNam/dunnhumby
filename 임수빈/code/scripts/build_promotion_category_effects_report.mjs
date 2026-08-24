import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const inputPath = path.join(root, "data", "processed", "promotion_category_effects_wide.csv");
const outputDir = path.join(root, "outputs", "promotion_category_prioritization");
await fs.mkdir(outputDir, { recursive: true });

const csvText = await fs.readFile(inputPath, "utf8");
const imported = await Workbook.fromCSV(csvText, { sheetName: "카테고리 효과" });
const sourceValues = imported.worksheets.getItem("카테고리 효과").getUsedRange(true).values;

const workbook = Workbook.create();
const summary = workbook.worksheets.add("1단계 요약");
const data = workbook.worksheets.add("카테고리 효과");
data.getRangeByIndexes(0, 0, sourceValues.length, sourceValues[0].length).values = sourceValues;

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["1단계 | 카테고리별 결합 프로모션 효과 계산"]];
summary.getRange("A3:B8").values = [
  ["분석 질문", "카테고리별로 전단+진열이 진열만·전단만보다 판매성과가 얼마나 높은가?"],
  ["분석 단위", "DEPARTMENT × COMMODITY_DESC"],
  ["전체 카테고리", null],
  ["두 비교 모두 가능", null],
  ["진열만 비교만 가능", null],
  ["전단만 비교만 가능", null],
];
summary.getRange("B5").formulas = [["=COUNTA('카테고리 효과'!$B$2:$B$253)"]];
summary.getRange("B6").formulas = [["=COUNTIF('카테고리 효과'!$E$2:$E$253,TRUE)"]];
summary.getRange("B7").formulas = [["=COUNTIFS('카테고리 효과'!$C$2:$C$253,TRUE,'카테고리 효과'!$D$2:$D$253,FALSE)"]];
summary.getRange("B8").formulas = [["=COUNTIFS('카테고리 효과'!$C$2:$C$253,FALSE,'카테고리 효과'!$D$2:$D$253,TRUE)"]];
summary.getRange("A10:H10").merge();
summary.getRange("A10").values = [["표 읽는 법"]];
summary.getRange("A11:B15").values = [
  ["vs_display_only", "전단+진열에서 진열만을 뺀 평균 차이"],
  ["vs_mailer_only", "전단+진열에서 전단만을 뺀 평균 차이"],
  ["sales_incidence_diff", "판매가 발생할 확률의 차이. 0.01은 +1%p"],
  ["revenue_diff", "상품·매장·주차 단위 평균 SALES_VALUE 차이"],
  ["주의", "이 단계는 효과 계산만 수행한다. 표본과 신뢰도 기준은 다음 단계에서 적용한다."],
];
summary.getRange("A17:H19").merge();
summary.getRange("A17").values = [["자료 출처: promotion_combination_category_effects.csv. 동일 상품·동일 매장에서 결합 프로모션 주차와 가장 가까운 단독 프로모션 주차(±4주)를 비교한 기존 결과를 카테고리별로 재구성했다."]];

const navy = "#17365D";
const lightBlue = "#D9EAF7";
summary.showGridLines = false;
data.showGridLines = false;
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, verticalAlignment: "center" };
summary.getRange("A1:H1").format.rowHeight = 32;
summary.getRange("A3:A8").format = { fill: lightBlue, font: { bold: true }, verticalAlignment: "center" };
summary.getRange("A10:H10").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A11:A15").format = { fill: lightBlue, font: { bold: true } };
summary.getRange("A17:H19").format = { fill: "#FFF2CC", font: { italic: true, color: "#7F6000" }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A3:B15").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 70;
summary.getRange("C:H").format.columnWidth = 5;
summary.freezePanes.freezeRows(1);

const rows = sourceValues.length;
const cols = sourceValues[0].length;
data.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
data.getRangeByIndexes(0, 0, rows, cols).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
data.getRange("A:A").format.columnWidth = 18;
data.getRange("B:B").format.columnWidth = 30;
data.getRange("C:E").format.columnWidth = 15;
data.getRange("F:S").format.columnWidth = 17;
data.getRange("F:H").format.numberFormat = "#,##0";
data.getRange("I:I").format.numberFormat = "0.000%";
data.getRange("J:L").format.numberFormat = "0.0000";
data.getRange("M:O").format.numberFormat = "#,##0";
data.getRange("P:P").format.numberFormat = "0.000%";
data.getRange("Q:S").format.numberFormat = "0.0000";
data.getRange(`I2:I${rows}`).conditionalFormats.add("colorScale", { colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"] });
data.getRange(`J2:J${rows}`).conditionalFormats.add("colorScale", { colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"] });
data.getRange(`P2:P${rows}`).conditionalFormats.add("colorScale", { colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"] });
data.getRange(`Q2:Q${rows}`).conditionalFormats.add("colorScale", { colors: ["#F4CCCC", "#FFF2CC", "#D9EAD3"] });
data.freezePanes.freezeRows(1);
data.freezePanes.freezeColumns(2);
data.tables.add(`A1:S${rows}`, true, "CategoryEffectsTable");

const check = await workbook.inspect({ kind: "table", range: "1단계 요약!A1:B17", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 4 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);

const summaryPreview = await workbook.render({ sheetName: "1단계 요약", range: "A1:H19", scale: 1.3, format: "png" });
await fs.writeFile(path.join(outputDir, "01_category_effects_summary.png"), new Uint8Array(await summaryPreview.arrayBuffer()));
const dataPreview = await workbook.render({ sheetName: "카테고리 효과", range: "A1:S18", scale: 0.8, format: "png" });
await fs.writeFile(path.join(outputDir, "01_category_effects_data.png"), new Uint8Array(await dataPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "01_promotion_category_effects.xlsx"));
