module shift_register_16bit (
    input wire clk,
    input wire data_in,
    output wire data_out
);

wire n1;
wire n2;
wire n3;
wire n4;
wire n5;
wire n6;
wire n7;
wire n8;
wire n9;
wire n10;
wire n11;
wire n12;
wire n13;
wire n14;
wire n15;

DFF U1 (n1, clk, data_in);
DFF U2 (n2, clk, n1);
DFF U3 (n3, clk, n2);
DFF U4 (n4, clk, n3);
DFF U5 (n5, clk, n4);
DFF U6 (n6, clk, n5);
DFF U7 (n7, clk, n6);
DFF U8 (n8, clk, n7);
DFF U9 (n9, clk, n8);
DFF U10 (n10, clk, n9);
DFF U11 (n11, clk, n10);
DFF U12 (n12, clk, n11);
DFF U13 (n13, clk, n12);
DFF U14 (n14, clk, n13);
DFF U15 (n15, clk, n14);
DFF U16 (data_out, clk, n15);

endmodule
