module shift_register_4bit (
    input wire enable,
    input wire data_in,
    output wire data_out
);

wire n1;
wire n2;
wire n3;

DFF U1 (n1, enable, data_in);
DFF U2 (n2, enable, n1);
DFF U3 (n3, enable, n2);
DFF U4 (data_out, enable, n3);

endmodule
