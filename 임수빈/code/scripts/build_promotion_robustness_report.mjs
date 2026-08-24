import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const dataDir = path.join(root, "data", "processed");
const outputDir = path.join(root, "outputs", "promotion_combination_robustness");
await fs.mkdir(outputDir, { recursive: true });

async function csvValues(file, sheetName) {
  const text = await fs.readFile(path.join(dataDir, file), "utf8");
  const temp = await Workbook.fromCSV(text, { sheetName });
  return temp.worksheets.getItem(sheetName).getUsedRange(true).values;
}

const testValues = await csvValues("promotion_robustness_tests.csv", "강건성 검정");
const exclusionValues = await csvValues("promotion_department_exclusion_tests.csv", "부문 제외 검정");
const workbook = Workbook.create();
const summary = workbook.worksheets.add("결론");
const tests = workbook.worksheets.add("강건성 검정");
const exclusions = workbook.worksheets.add("부문 제외 검정");

tests.getRangeByIndexes(0, 0, testValues.length, testValues[0].length).values = testValues;
exclusions.getRangeByIndexes(0, 0, exclusionValues.length, exclusionValues[0].length).values = exclusionValues;

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["진열+전단 결합 프로모션 강건성 검증"]];
summary.getRange("A3:B8").values = [
  ["검증 가설", "같은 상품·매장에서 진열과 전단을 함께 적용한 주차는 단독 적용 주차보다 판매발생률과 매출이 높다."],
  ["매칭 범위", "가장 가까운 단독 프로모션 주차 ±1주, ±2주, ±4주"],
  ["핵심 비교", "진열+전단 - 진열만 / 진열+전단 - 전단만"],
  ["강건성 검정 수", null],
  ["핵심 검정 통과 수", null],
  ["최종 판정", null],
];
summary.getRange("B6").formulas = [["=COUNTIFS('강건성 검정'!$C$2:$C$25,\"판매발생률\")+COUNTIFS('강건성 검정'!$C$2:$C$25,\"매출\")"]];
summary.getRange("B7").formulas = [["=COUNTIFS('강건성 검정'!$C$2:$C$25,\"판매발생률\",'강건성 검정'!$I$2:$I$25,TRUE)+COUNTIFS('강건성 검정'!$C$2:$C$25,\"매출\",'강건성 검정'!$I$2:$I$25,TRUE)"]];
summary.getRange("B8").formulas = [["=IF(AND(B6=B7,COUNTIF('부문 제외 검정'!$J$2:$J$73,FALSE)=0),\"가설 지지: 매칭 범위와 대형 부문 제외에도 결론 유지\",\"일부 조건에서 결론 변화: 적용 범위 제한 필요\")"]];
summary.getRange("A10:H10").merge();
summary.getRange("A10").values = [["핵심 수치 (상품 단위 평균 효과)"]];
summary.getRange("A11:F17").values = [
  ["허용 범위", "비교", "판매발생률 차이", "매출 차이", "판매발생률 p값", "매출 p값"],
  [1, "진열+전단 - 진열만", 0.005515, 0.015494, 5.070369e-44, 6.402641e-19],
  [1, "진열+전단 - 전단만", 0.003123, 0.008212, 1.323870e-10, 8.545201e-5],
  [2, "진열+전단 - 진열만", 0.005609, 0.015809, 8.322707e-47, 6.217019e-21],
  [2, "진열+전단 - 전단만", 0.003136, 0.007824, 4.020032e-12, 4.635104e-5],
  [4, "진열+전단 - 진열만", 0.005657, 0.015507, 3.512803e-51, 1.335506e-21],
  [4, "진열+전단 - 전단만", 0.004223, 0.011851, 3.444417e-23, 7.024962e-9],
];
summary.getRange("A19:H21").merge();
summary.getRange("A19").values = [["해석 주의: 이 결과는 동일 상품·매장의 가까운 주차를 비교한 관찰자료 분석이다. 결합 프로모션의 효과가 여러 조건에서 반복되지만, 무작위 배정이 아니므로 순수 인과효과나 비용 대비 수익성을 확정하지는 않는다."]];

const navy = "#17365D";
const blue = "#D9EAF7";
const green = "#E2F0D9";
for (const sheet of [summary, tests, exclusions]) sheet.showGridLines = false;
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, verticalAlignment: "center" };
summary.getRange("A1:H1").format.rowHeight = 32;
summary.getRange("A3:A8").format = { fill: blue, font: { bold: true }, verticalAlignment: "center" };
summary.getRange("B8").format = { fill: green, font: { bold: true, color: "#274E13" }, wrapText: true };
summary.getRange("A10:H10").format = { fill: navy, font: { bold: true, color: "#FFFFFF" } };
summary.getRange("A11:F11").format = { fill: blue, font: { bold: true } };
summary.getRange("C12:C17").format.numberFormat = "0.000%";
summary.getRange("D12:D17").format.numberFormat = "0.0000";
summary.getRange("E12:F17").format.numberFormat = "0.00E+00";
summary.getRange("A19:H21").format = { fill: "#FFF2CC", font: { italic: true, color: "#7F6000" }, wrapText: true, verticalAlignment: "top" };
summary.getRange("A3:B8").format.borders = { preset: "outside", style: "thin", color: "#A6A6A6" };
summary.getRange("A11:F17").format.borders = { preset: "inside", style: "thin", color: "#D9D9D9" };
summary.getRange("A1:H21").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 18;
summary.getRange("B:B").format.columnWidth = 52;
summary.getRange("C:F").format.columnWidth = 18;
summary.getRange("G:H").format.columnWidth = 4;
summary.freezePanes.freezeRows(1);

function styleDataSheet(sheet, rows, cols) {
  sheet.getRangeByIndexes(0, 0, 1, cols).format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, wrapText: true };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
  sheet.getRangeByIndexes(0, 0, rows, cols).format.autofitColumns();
  sheet.getRangeByIndexes(0, 0, rows, cols).format.autofitRows();
  sheet.getRangeByIndexes(0, 0, rows, cols).format.columnWidth = 16;
  sheet.freezePanes.freezeRows(1);
}
styleDataSheet(tests, testValues.length, testValues[0].length);
styleDataSheet(exclusions, exclusionValues.length, exclusionValues[0].length);
tests.getRange("B:B").format.columnWidth = 24;
exclusions.getRange("B:B").format.columnWidth = 24;
exclusions.getRange("C:C").format.columnWidth = 20;

const check = await workbook.inspect({ kind: "table", range: "결론!A1:F21", include: "values,formulas", tableMaxRows: 24, tableMaxCols: 8 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "결론", range: "A1:H21", scale: 1.5, format: "png" });
await fs.writeFile(path.join(outputDir, "promotion_combination_robustness_preview.png"), new Uint8Array(await preview.arrayBuffer()));
const testsPreview = await workbook.render({ sheetName: "강건성 검정", range: "A1:I16", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "promotion_robustness_tests_preview.png"), new Uint8Array(await testsPreview.arrayBuffer()));
const exclusionsPreview = await workbook.render({ sheetName: "부문 제외 검정", range: "A1:J16", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "promotion_department_exclusion_preview.png"), new Uint8Array(await exclusionsPreview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "promotion_combination_robustness_report.xlsx"));
