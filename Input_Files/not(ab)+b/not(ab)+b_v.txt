module not(a*b)+b (
    input wire a,
    input wire b,
    output wire y
);

wire n1;
wire n2;

and U1 (n1, a, b); // Metal 1
not U2 (n2, n1);   // Metal 1
or U3 (y, n2, b);  // Metal 2

endmodule
